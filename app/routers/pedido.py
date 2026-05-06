import json
import os
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy import or_, cast, String, func, text
from datetime import datetime, timezone
from io import BytesIO
import textwrap
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from app.database import get_db
from app.models.producto import Producto
from app.models.barrio import Barrio
from app.models.cliente import Cliente
from app.models.empresa import Empresa
from app.models.pedido import Pedido
from app.models.pedidodetalle import PedidoDetalle
from app.models.produccion import Produccion
from app.models.transicionestadopedido import TransicionEstadoPedido
from app.models.estadopedido import EstadoPedido
from app.models.entrega import Entrega

from app.schemas.pedido import (
    PedidoCheckoutRequest,
    PedidoCheckoutResponse,
    PedidoCreate,
    PedidoListResponse,
    PedidoListItem,
    PedidoDetalleResponse,
    PedidoDetalleProducto,
    RechazarPedidoRequest,
)
from app.services.pedido_service import checkout_pedido, generar_numeracion_pedido
from app.services import produccion_service
from app.services.produccion_service import asegurar_produccion_desde_pedido_aprobado_por_detalle
from app.core.logger import get_logger
from app.core.ordering import sort_operativo
from app.core.security import assert_same_empresa, get_current_auth_context, is_super_admin_context, require_module_access
from app.middlewares.rate_limit import limiter

router = APIRouter()
pedido_logger = get_logger("pedido")

FLORA_EMPRESA_ID = 3
FLORA_PAYMENT_METHODS = {
    "Cuenta por cobrar",
    "Efectivo",
    "Canje",
    "Contraentrega",
    "Cotizacion",
    "Obsequio",
    "Paypal",
    "Link bold",
    "Link payu",
    "Link wompi",
    "Datafono credibanco",
    "Datafono Bold",
    "Transferencia 0257",
    "Transferencia 0005",
    "Transferencia 3220",
    "Transferencia 4038",
    "Transferencia 4966",
    "Transferencia 3671",
    "Transferencia 6913",
    "Transferencia 5431",
    "Transferencia 1340",
    "Transferencia Jaque",
    "Transferencia QR",
    "Anulado",
}
FLORA_SALES_CHANNELS = {
    "Huawei",
    "Samsung",
    "Andrea",
    "Página Web",
    "Presencial",
    "Rappi",
}


def _tenant_order_rules(empresa_id: int) -> dict:
    if int(empresa_id) == FLORA_EMPRESA_ID:
        return {
            "require_payment_before_approval": True,
            "require_sales_channel_before_approval": True,
        }
    return {
        "require_payment_before_approval": False,
        "require_sales_channel_before_approval": False,
    }


def _activo_truthy(column):
    return func.lower(cast(column, String)).in_(["true", "t", "1"])


def _numero_pedido_humano(pedido: Pedido) -> str:
    if pedido.codigoPedido:
        return str(pedido.codigoPedido)
    if pedido.numeroPedido is not None and int(pedido.numeroPedido or 0) > 0:
        return f"PED-{int(pedido.numeroPedido)}"
    return f"PED-{int(pedido.idPedido):06d}"


def _estado_pedido_tiene_numeracion_visible(estado_nombre: str | None) -> bool:
    estado = str(estado_nombre or "").strip().upper()
    return estado not in {"", "CREADO", "PENDIENTE"}


def _numero_pedido_valor(pedido: Pedido, estado_nombre: str | None = None) -> int | None:
    if not _estado_pedido_tiene_numeracion_visible(estado_nombre):
        return None
    if pedido.numeroPedido is not None and int(pedido.numeroPedido or 0) > 0:
        return int(pedido.numeroPedido)
    return None


def _fecha_pedido_str(value: datetime | None) -> str | None:
    if not value:
        return None
    return value.date().isoformat()


def _hora_pedido_str(value: datetime | None) -> str | None:
    if not value:
        return None
    return value.strftime("%H:%M:%S")


def _fecha_hora_humano(value: datetime | None) -> str:
    if not value:
        return "No especificada"
    return value.strftime("%d/%m/%Y %H:%M")


def _money_cop(value: float | int | None) -> str:
    number = int(round(float(value or 0)))
    return f"${number:,}".replace(",", ".")


def _estado_permite_factura(value: str | None) -> bool:
    estado = str(value or "").strip().upper()
    return estado in {"APROBADO", "PAGADO"}


def _render_factura_pdf(lines: list[str]) -> bytes:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    margin_x = 40
    y = height - 45

    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(margin_x, y, "FLORA - TIENDA DE FLORES")
    y -= 24

    pdf.setFont("Helvetica", 10)
    max_chars = 88

    for raw_line in lines:
        wrapped = textwrap.wrap(str(raw_line or ""), width=max_chars) or [""]
        for line in wrapped:
            if y < 45:
                pdf.showPage()
                pdf.setFont("Helvetica", 10)
                y = height - 45
            pdf.drawString(margin_x, y, line)
            y -= 14
        y -= 2

    pdf.save()
    buffer.seek(0)
    return buffer.getvalue()


def _buscar_estado_por_nombre(db: Session, *nombres: str) -> EstadoPedido | None:
    nombres_upper = [nombre.upper() for nombre in nombres]
    return (
        db.query(EstadoPedido)
        .filter(func.upper(EstadoPedido.nombreEstado).in_(nombres_upper), _activo_truthy(EstadoPedido.activo))
        .order_by(EstadoPedido.idEstadoPedido.asc())
        .first()
    )


def _ids_estado_pendiente(db: Session) -> set[int]:
    estados = (
        db.query(EstadoPedido)
        .filter(func.upper(EstadoPedido.nombreEstado).in_(["PENDIENTE", "CREADO"]), _activo_truthy(EstadoPedido.activo))
        .all()
    )
    return {int(estado.idEstadoPedido) for estado in estados}


def _buscar_estado_inicial_pedido(db: Session) -> EstadoPedido | None:
    return (
        db.query(EstadoPedido)
        .filter(func.upper(EstadoPedido.nombreEstado).in_(["CREADO", "PENDIENTE"]), _activo_truthy(EstadoPedido.activo))
        .order_by(EstadoPedido.idEstadoPedido.asc())
        .first()
    )


def _estado_pedido_nombre(db: Session, estado_pedido_id: int | None) -> str:
    if estado_pedido_id is None:
        return ""
    estado = db.query(EstadoPedido).filter(EstadoPedido.idEstadoPedido == int(estado_pedido_id)).first()
    return str((estado.nombreEstado if estado else "") or "").strip().upper()


def _transicion_pedido_permitida(db: Session, empresa_id: int, origen_id: int | None, destino_id: int | None) -> bool:
    if origen_id is None or destino_id is None:
        return False

    origen_id = int(origen_id)
    destino_id = int(destino_id)
    if origen_id == destino_id:
        return True

    transitions = db.execute(
        text(
            """
            SELECT estado_origen_id, estado_destino_id
            FROM petalops.transicion_estado_pedido
            WHERE empresa_id = :empresa_id
            """
        ),
        {"empresa_id": int(empresa_id)},
    ).fetchall()
    if transitions:
        return any(int(row[0]) == origen_id and int(row[1]) == destino_id for row in transitions)

    origen = _estado_pedido_nombre(db, origen_id)
    destino = _estado_pedido_nombre(db, destino_id)
    fallback = {
        "CREADO": {"APROBADO", "PAGADO", "RECHAZADO", "CANCELADO"},
        "PENDIENTE": {"APROBADO", "PAGADO", "RECHAZADO", "CANCELADO"},
        "APROBADO": {"CANCELADO", "PAGADO"},
        "PAGADO": {"CANCELADO"},
    }
    return destino in fallback.get(origen, set())


def _estado_pedido_editable(db: Session, estado_pedido_id: int | None) -> bool:
    return _estado_pedido_nombre(db, estado_pedido_id) not in {"ENTREGADO", "CANCELADO", "RECHAZADO"}


def _is_lock_not_available_error(exc: OperationalError) -> bool:
    original = getattr(exc, "orig", None)
    return getattr(original, "pgcode", None) == "55P03"


def _dias_anticipacion_produccion() -> int:
    return max(int(os.getenv("PRODUCCION_DIAS_ANTICIPACION", "0")), 0)


def _scheduled_entrega_datetime(entrega: Entrega | None) -> datetime | None:
    if not entrega:
        return None
    return entrega.reprogramadaPara or entrega.fechaEntregaProgramada or entrega.fechaEntrega


def _parse_iso_date(value: str) -> datetime:
    raw = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "FECHA_INVALIDA", "message": "Formato de fecha inválido"},
        ) from exc

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _cliente_identificacion_fallback(identificacion: str | None, telefono: str | None) -> str:
    value = str(identificacion or "").strip()
    if value:
        return value
    phone = str(telefono or "").strip()
    if phone:
        return phone
    return f"TMP-{int(datetime.now(timezone.utc).timestamp())}"


def _numero_pedido_temporal() -> int:
    return -int(datetime.now(timezone.utc).timestamp() * 1000000)


def _find_branch_product_price(db: Session, *, empresa_id: int, sucursal_id: int, producto_id: int) -> Decimal:
    row = db.execute(
        text(
            """
            SELECT ps.precio
            FROM petalops.producto_sucursal ps
            JOIN petalops.producto p
              ON p.id_producto = ps.producto_id
            WHERE p.id_producto = :producto_id
              AND p.empresa_id = :empresa_id
              AND ps.sucursal_id = :sucursal_id
              AND lower(CAST(p.activo AS VARCHAR)) IN ('true', 't', '1')
              AND lower(CAST(ps.activo AS VARCHAR)) IN ('true', 't', '1')
            LIMIT 1
            """
        ),
        {
            "producto_id": int(producto_id),
            "empresa_id": int(empresa_id),
            "sucursal_id": int(sucursal_id),
        },
    ).first()
    if not row or row[0] is None:
        raise HTTPException(
            status_code=400,
            detail={"code": "PRODUCTO_PRICE_NOT_FOUND", "message": "No se encontró precio activo para ese arreglo en la sucursal"},
        )
    return Decimal(str(row[0]))


def _normalize_ident_type(value: str | None) -> str | None:
    raw = str(value or "").strip().upper()
    if not raw:
        return None
    if raw in {"CC", "CEDULA", "CÉDULA"}:
        return "CC"
    if raw == "NIT":
        return "NIT"
    return raw


def _tax_rate_for_producto(producto: Producto | None) -> Decimal:
    if not producto:
        return Decimal("0.00")
    raw_rate = producto.porcentajeIva
    # Fallback operativo: varios productos legacy no tienen porcentaje_iva cargado
    # y para correcciones manuales a NIT se aplica la tarifa general.
    if raw_rate is None:
        return Decimal("19.00")
    rate = Decimal(str(raw_rate))
    if rate <= 0:
        return Decimal("19.00")
    return rate


def _iva_unitario_for_producto(precio_unitario: Decimal, producto: Producto | None) -> Decimal:
    if precio_unitario <= 0:
        return Decimal("0.00")

    rate = _tax_rate_for_producto(producto)
    if rate <= 0:
        return Decimal("0.00")

    if bool(getattr(producto, "ivaIncluido", False)):
        divisor = Decimal("1.00") + (rate / Decimal("100"))
        return (precio_unitario - (precio_unitario / divisor)).quantize(Decimal("0.01"))

    return ((precio_unitario * rate) / Decimal("100")).quantize(Decimal("0.01"))


def _recalculate_pedido_financials(db: Session, *, pedido: Pedido, aplica_iva: bool) -> None:
    detalles = (
        db.query(PedidoDetalle)
        .filter(
            PedidoDetalle.pedidoID == int(pedido.idPedido),
            PedidoDetalle.empresaID == int(pedido.empresaID),
        )
        .all()
    )

    producto_ids = [int(detalle.productoID) for detalle in detalles if detalle.productoID is not None]
    productos = (
        db.query(Producto)
        .filter(
            Producto.idProducto.in_(producto_ids) if producto_ids else text("1=0"),
            Producto.empresaID == int(pedido.empresaID),
        )
        .all()
    )
    producto_map = {int(producto.idProducto): producto for producto in productos}

    total_bruto = Decimal("0.00")
    total_iva = Decimal("0.00")

    for detalle in detalles:
        cantidad = Decimal(str(detalle.cantidad or 0))
        precio_unitario = Decimal(str(detalle.precioUnitario or 0))
        detalle.subtotal = (precio_unitario * cantidad).quantize(Decimal("0.01"))
        detalle.ivaUnitario = (
            _iva_unitario_for_producto(precio_unitario, producto_map.get(int(detalle.productoID)))
            if aplica_iva
            else Decimal("0.00")
        )
        total_bruto += Decimal(str(detalle.subtotal or 0))
        total_iva += Decimal(str(detalle.ivaUnitario or 0)) * cantidad

    pedido.totalBruto = total_bruto.quantize(Decimal("0.01"))
    pedido.totalIva = total_iva.quantize(Decimal("0.01"))
    pedido.totalNeto = (
        pedido.totalBruto
        + pedido.totalIva
        + Decimal(str(getattr(pedido, "costoDomicilio", 0) or 0))
    ).quantize(Decimal("0.01"))


def _parse_payment_methods(value: str | None) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    return [part.strip() for part in raw.split("|") if str(part).strip()]


def _table_exists(db: Session, table_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'petalops'
              AND table_name = :table_name
            LIMIT 1
            """
        ),
        {"table_name": table_name},
    ).first()
    return bool(row)


def _flora_phase2_ready(db: Session) -> bool:
    return all(
        _table_exists(db, table_name)
        for table_name in ("metodo_pago_catalogo", "pago_metodo", "canal_venta", "pedido_canal_venta")
    )


def _empresa_menu_ready(db: Session) -> bool:
    return _table_exists(db, "empresa_menu")


def _load_empresa_menu_rows(db: Session, *, empresa_id: int, seccion: str = "pedido_detalle") -> list[dict]:
    if not _empresa_menu_ready(db):
        return []

    rows = db.execute(
        text(
            """
            SELECT codigo, titulo, seccion, tipo_control, opciones_json, requerido_aprobacion, activo, orden
            FROM petalops.empresa_menu
            WHERE empresa_id = :empresa_id
              AND seccion = :seccion
              AND activo = TRUE
            ORDER BY orden ASC, titulo ASC
            """
        ),
        {"empresa_id": int(empresa_id), "seccion": seccion},
    ).mappings().all()

    result = []
    for row in rows:
        opciones = row.get("opciones_json")
        if isinstance(opciones, str):
            try:
                opciones = json.loads(opciones)
            except ValueError:
                opciones = []
        if not isinstance(opciones, list):
            opciones = []
        result.append(
            {
                "codigo": str(row["codigo"]),
                "titulo": str(row["titulo"]),
                "seccion": str(row["seccion"]),
                "tipoControl": str(row["tipo_control"]),
                "opciones": [str(item) for item in opciones if str(item).strip()],
                "requeridoAprobacion": bool(row["requerido_aprobacion"]),
                "activo": bool(row["activo"]),
                "orden": int(row["orden"] or 0),
            }
        )
    return result


def _load_empresa_menu_config(db: Session, *, empresa_id: int, seccion: str = "pedido_detalle") -> dict[str, dict]:
    rows = _load_empresa_menu_rows(db, empresa_id=int(empresa_id), seccion=seccion)
    return {row["codigo"]: row for row in rows}


def _pedido_detalle_has_observaciones_personalizados(db: Session) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'petalops'
              AND table_name = 'pedido_detalle'
              AND column_name = 'observaciones_personalizados'
            LIMIT 1
            """
        )
    ).first()
    return bool(row)


def _sanitize_producto_observacion(value: str | None, producto: Producto | None = None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    descripcion = str(getattr(producto, "descripcion", "") or "").strip()
    if descripcion and text.casefold() == descripcion.casefold():
        return None
    return text


def _is_custom_producto(producto: Producto | None) -> bool:
    if not producto:
        return False
    raw = " ".join(
        str(value or "").strip().lower()
        for value in (
            getattr(producto, "codigoProducto", None),
            getattr(producto, "nombreProducto", None),
            getattr(producto, "descripcion", None),
        )
    )
    return "personalizado" in raw or "personalizada" in raw


def _resolve_costo_domicilio(
    db: Session,
    *,
    empresa_id: int,
    sucursal_id: int,
    tipo_entrega: str | None,
    barrio_id: int | None = None,
    barrio_nombre: str | None = None,
) -> Decimal:
    tipo = str(tipo_entrega or "").strip().lower()
    if tipo and tipo != "domicilio":
        return Decimal("0.00")

    if barrio_id is not None:
        barrio = (
            db.query(Barrio)
            .filter(
                Barrio.idBarrio == int(barrio_id),
                Barrio.empresaID == int(empresa_id),
                Barrio.sucursalID == int(sucursal_id),
            )
            .first()
        )
        if barrio and barrio.costoDomicilio is not None:
            return Decimal(str(barrio.costoDomicilio)).quantize(Decimal("0.01"))

    nombre = str(barrio_nombre or "").strip()
    if nombre:
        barrio = (
            db.query(Barrio)
            .filter(
                Barrio.empresaID == int(empresa_id),
                Barrio.sucursalID == int(sucursal_id),
                func.lower(Barrio.nombreBarrio) == nombre.lower(),
            )
            .first()
        )
        if barrio and barrio.costoDomicilio is not None:
            return Decimal(str(barrio.costoDomicilio)).quantize(Decimal("0.01"))

    return Decimal("0.00")


def _pedido_domicilio_valor(pedido: Pedido) -> Decimal:
    costo = Decimal(str(getattr(pedido, "costoDomicilio", 0) or 0))
    if costo > 0:
        return costo.quantize(Decimal("0.01"))
    total = Decimal(str(pedido.totalNeto or 0))
    arreglos = Decimal(str(pedido.totalBruto or 0)) + Decimal(str(pedido.totalIva or 0))
    diferencia = (total - arreglos).quantize(Decimal("0.01"))
    return diferencia if diferencia > 0 else Decimal("0.00")


def _tenant_order_rules(db: Session, empresa_id: int) -> dict:
    config = _load_empresa_menu_config(db, empresa_id=int(empresa_id))
    payment_field = config.get("pedido_metodos_pago")
    channel_field = config.get("pedido_canal_venta")
    return {
        "require_payment_before_approval": bool(payment_field and payment_field["requeridoAprobacion"]),
        "require_sales_channel_before_approval": bool(channel_field and channel_field["requeridoAprobacion"]),
    }


def _safe_parse_json(raw: str | None) -> dict:
    text_value = str(raw or "").strip()
    if not text_value:
        return {}
    try:
        parsed = json.loads(text_value)
    except (TypeError, ValueError):
        return {"_legacyRawRespuesta": text_value}
    return parsed if isinstance(parsed, dict) else {"_legacyRawRespuesta": parsed}


def _extract_canal_flora(raw_respuesta: str | None) -> str | None:
    payload = _safe_parse_json(raw_respuesta)
    metadata = payload.get("_petalopsMetadata")
    if not isinstance(metadata, dict):
        return None
    value = metadata.get("canalFlora")
    text_value = str(value or "").strip()
    return text_value or None


def _serialize_pago_metadata(raw_respuesta: str | None, *, canal_flora: str | None) -> str | None:
    payload = _safe_parse_json(raw_respuesta)
    metadata = payload.get("_petalopsMetadata")
    if not isinstance(metadata, dict):
        metadata = {}

    cleaned_channel = str(canal_flora or "").strip()
    if cleaned_channel:
        metadata["canalFlora"] = cleaned_channel
    else:
        metadata.pop("canalFlora", None)

    if metadata:
        payload["_petalopsMetadata"] = metadata
    else:
        payload.pop("_petalopsMetadata", None)

    if not payload:
        return None
    return json.dumps(payload, ensure_ascii=False)


def _load_pago_resumen(db: Session, *, pedido_id: int, empresa_id: int) -> dict:
    if _flora_phase2_ready(db):
        metodos_rows = db.execute(
            text(
                """
                SELECT mpc.nombre
                FROM petalops.pago_metodo pm
                JOIN petalops.metodo_pago_catalogo mpc
                  ON mpc.id_metodo_pago = pm.metodo_pago_id
                WHERE pm.empresa_id = :empresa_id
                  AND pm.pedido_id = :pedido_id
                ORDER BY pm.orden ASC, mpc.orden ASC, mpc.nombre ASC
                """
            ),
            {"empresa_id": int(empresa_id), "pedido_id": int(pedido_id)},
        ).all()
        canal_row = db.execute(
            text(
                """
                SELECT cv.nombre
                FROM petalops.pedido_canal_venta pcv
                JOIN petalops.canal_venta cv
                  ON cv.id_canal_venta = pcv.canal_venta_id
                WHERE pcv.empresa_id = :empresa_id
                  AND pcv.pedido_id = :pedido_id
                LIMIT 1
                """
            ),
            {"empresa_id": int(empresa_id), "pedido_id": int(pedido_id)},
        ).first()

        metodos_pago = [str(row[0]).strip() for row in metodos_rows if row and row[0] is not None]
        if metodos_pago or canal_row:
            metodo_pago = " | ".join(metodos_pago) if metodos_pago else None
            return {
                "metodoPago": metodo_pago,
                "metodosPago": metodos_pago,
                "cuentaBancaria": ", ".join([item for item in metodos_pago if item.startswith("Transferencia ")]) or None,
                "canalFlora": (str(canal_row[0]).strip() if canal_row and canal_row[0] is not None else None),
            }

    row = db.execute(
        text(
            """
            SELECT metodo_pago, proveedor, referencia, raw_respuesta
            FROM petalops.pago
            WHERE pedido_id = :pedido_id
              AND empresa_id = :empresa_id
            LIMIT 1
            """
        ),
        {"pedido_id": int(pedido_id), "empresa_id": int(empresa_id)},
    ).mappings().first()

    if not row:
        return {
            "metodoPago": None,
            "metodosPago": [],
            "cuentaBancaria": None,
            "canalFlora": None,
        }

    metodo_pago = str(row.get("metodo_pago") or "").strip() or None
    metodos_pago = _parse_payment_methods(metodo_pago)
    return {
        "metodoPago": metodo_pago,
        "metodosPago": metodos_pago,
        "cuentaBancaria": ", ".join([item for item in metodos_pago if item.startswith("Transferencia ")]) or None,
        "canalFlora": _extract_canal_flora(row.get("raw_respuesta")),
    }


def _approval_gate_summary(db: Session, *, pedido_id: int, empresa_id: int) -> dict:
    rules = _tenant_order_rules(db, int(empresa_id))
    pago_resumen = _load_pago_resumen(db, pedido_id=int(pedido_id), empresa_id=int(empresa_id))

    missing = []
    if rules["require_payment_before_approval"] and not pago_resumen["metodosPago"]:
        missing.append("método de pago")
    if rules["require_sales_channel_before_approval"] and not pago_resumen["canalFlora"]:
        missing.append("medio de venta")

    if not missing:
        return {"puedeAprobar": True, "motivo": None, "pagoResumen": pago_resumen}

    motivo = "Debes confirmar " + " y ".join(missing) + " antes de aprobar."
    return {"puedeAprobar": False, "motivo": motivo, "pagoResumen": pago_resumen}


def _upsert_pago_flora(
    db: Session,
    *,
    pedido_id: int,
    empresa_id: int,
    monto: Decimal,
    metodos_pago: list[str],
    canal_flora: str | None,
):
    row = db.execute(
        text(
            """
            SELECT id_pago, raw_respuesta
            FROM petalops.pago
            WHERE pedido_id = :pedido_id
              AND empresa_id = :empresa_id
            LIMIT 1
            """
        ),
        {"pedido_id": int(pedido_id), "empresa_id": int(empresa_id)},
    ).mappings().first()

    metodo_pago = " | ".join(metodos_pago) if metodos_pago else None
    raw_respuesta = _serialize_pago_metadata(row.get("raw_respuesta") if row else None, canal_flora=canal_flora)

    if row:
        db.execute(
            text(
                """
                UPDATE petalops.pago
                SET metodo_pago = :metodo_pago,
                    raw_respuesta = :raw_respuesta,
                    monto = :monto,
                    updated_at = NOW()
                WHERE id_pago = :id_pago
                  AND empresa_id = :empresa_id
                """
            ),
            {
                "id_pago": int(row["id_pago"]),
                "empresa_id": int(empresa_id),
                "metodo_pago": metodo_pago,
                "raw_respuesta": raw_respuesta,
                "monto": monto,
            },
        )
    else:
        db.execute(
            text(
                """
                INSERT INTO petalops.pago (
                    empresa_id,
                    pedido_id,
                    proveedor,
                    referencia,
                    transaccion_id,
                    moneda,
                    monto,
                    metodo_pago,
                    checkouturl,
                    raw_respuesta,
                    estado_pago_id,
                    fecha_pago,
                    created_at,
                    updated_at
                ) VALUES (
                    :empresa_id,
                    :pedido_id,
                    'manual',
                    NULL,
                    NULL,
                    'COP',
                    :monto,
                    :metodo_pago,
                    NULL,
                    :raw_respuesta,
                    NULL,
                    NOW(),
                    NOW(),
                    NOW()
                )
                RETURNING id_pago
                """
            ),
            {
                "empresa_id": int(empresa_id),
                "pedido_id": int(pedido_id),
                "monto": monto,
                "metodo_pago": metodo_pago,
                "raw_respuesta": raw_respuesta,
            },
        )

    if not _flora_phase2_ready(db):
        return

    pago_row = db.execute(
        text(
            """
            SELECT id_pago
            FROM petalops.pago
            WHERE pedido_id = :pedido_id
              AND empresa_id = :empresa_id
            LIMIT 1
            """
        ),
        {"pedido_id": int(pedido_id), "empresa_id": int(empresa_id)},
    ).first()
    if not pago_row:
        return
    pago_id = int(pago_row[0])

    if metodos_pago:
        metodo_catalog_rows = db.execute(
            text(
                """
                SELECT id_metodo_pago, nombre
                FROM petalops.metodo_pago_catalogo
                WHERE empresa_id = :empresa_id
                  AND nombre = ANY(:names)
                """
            ),
            {"empresa_id": int(empresa_id), "names": metodos_pago},
        ).mappings().all()
        metodo_by_name = {str(row["nombre"]).strip(): int(row["id_metodo_pago"]) for row in metodo_catalog_rows}
    else:
        metodo_by_name = {}

    db.execute(
        text(
            """
            DELETE FROM petalops.pago_metodo
            WHERE empresa_id = :empresa_id
              AND pedido_id = :pedido_id
            """
        ),
        {"empresa_id": int(empresa_id), "pedido_id": int(pedido_id)},
    )

    for index, metodo in enumerate(metodos_pago, start=1):
        metodo_id = metodo_by_name.get(metodo)
        if metodo_id is None:
            continue
        db.execute(
            text(
                """
                INSERT INTO petalops.pago_metodo (
                    empresa_id,
                    pago_id,
                    pedido_id,
                    metodo_pago_id,
                    orden,
                    created_at,
                    updated_at
                ) VALUES (
                    :empresa_id,
                    :pago_id,
                    :pedido_id,
                    :metodo_pago_id,
                    :orden,
                    NOW(),
                    NOW()
                )
                """
            ),
            {
                "empresa_id": int(empresa_id),
                "pago_id": pago_id,
                "pedido_id": int(pedido_id),
                "metodo_pago_id": metodo_id,
                "orden": index,
            },
        )

    db.execute(
        text(
            """
            DELETE FROM petalops.pedido_canal_venta
            WHERE empresa_id = :empresa_id
              AND pedido_id = :pedido_id
            """
        ),
        {"empresa_id": int(empresa_id), "pedido_id": int(pedido_id)},
    )

    if canal_flora:
        canal_row = db.execute(
            text(
                """
                SELECT id_canal_venta
                FROM petalops.canal_venta
                WHERE empresa_id = :empresa_id
                  AND nombre = :nombre
                LIMIT 1
                """
            ),
            {"empresa_id": int(empresa_id), "nombre": canal_flora},
        ).first()
        if canal_row:
            db.execute(
                text(
                    """
                    INSERT INTO petalops.pedido_canal_venta (
                        empresa_id,
                        pedido_id,
                        canal_venta_id,
                        created_at,
                        updated_at
                    ) VALUES (
                        :empresa_id,
                        :pedido_id,
                        :canal_venta_id,
                        NOW(),
                        NOW()
                    )
                    """
                ),
                {
                    "empresa_id": int(empresa_id),
                    "pedido_id": int(pedido_id),
                    "canal_venta_id": int(canal_row[0]),
                },
            )


@router.get("/pedidos", response_model=PedidoListResponse, dependencies=[Depends(require_module_access("pedidos", "puedeVer"))])
@limiter.limit("100/minute")
def listar_pedidos(
    request: Request,
    empresa_id: int = Query(..., alias="empresaID"),
    sucursal_id: int | None = Query(None, alias="sucursalID"),
    estado: str | None = Query(None),
    q: str | None = Query(None),
    fecha_desde: datetime | None = Query(None, alias="fechaDesde"),
    fecha_hasta: datetime | None = Query(None, alias="fechaHasta"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100, alias="pageSize"),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):  

    assert_same_empresa(auth, empresa_id)
    base = (
        db.query(
            Pedido.idPedido,
            Pedido.fechaPedido,
            text(
                """
                CASE
                    WHEN petalops.pedido.numero_pedido > 0
                     AND UPPER(COALESCE(petalops.estado_pedido.nombre_estado, '')) NOT IN ('CREADO', 'PENDIENTE')
                    THEN 1
                    ELSE 0
                END AS "numeroOrdenFlag"
                """
            ),
            text(
                """
                CASE
                    WHEN petalops.pedido.numero_pedido > 0
                     AND UPPER(COALESCE(petalops.estado_pedido.nombre_estado, '')) NOT IN ('CREADO', 'PENDIENTE')
                    THEN petalops.pedido.numero_pedido
                    ELSE NULL
                END AS "numeroPedidoOrden"
                """
            ),
            text(
                """
                CASE
                    WHEN petalops.pedido.numero_pedido > 0
                     AND UPPER(COALESCE(petalops.estado_pedido.nombre_estado, '')) NOT IN ('CREADO', 'PENDIENTE')
                    THEN petalops.pedido.numero_pedido
                    ELSE petalops.pedido.id_pedido
                END AS "ordenListado"
                """
            ),
        )
        .outerjoin(Cliente, Cliente.idCliente == Pedido.clienteID)
        .outerjoin(Entrega, Entrega.pedidoID == Pedido.idPedido)
        .outerjoin(EstadoPedido, EstadoPedido.idEstadoPedido == Pedido.estadoPedidoID)
        .filter(Pedido.empresaID == empresa_id)
    )

    if sucursal_id is not None:
        base = base.filter(Pedido.sucursalID == sucursal_id)

    if estado:
        base = base.filter(func.upper(EstadoPedido.nombreEstado) == estado.upper())

    if fecha_desde:
        base = base.filter(Pedido.fechaPedido >= fecha_desde)

    if fecha_hasta:
        base = base.filter(Pedido.fechaPedido <= fecha_hasta)

    if q:
        term = f"%{q.strip()}%"
        base = (
            base.outerjoin(PedidoDetalle, PedidoDetalle.pedidoID == Pedido.idPedido)
            .outerjoin(Producto, Producto.idProducto == PedidoDetalle.productoID)
            .filter(
                or_(
                    cast(Pedido.idPedido, String).ilike(term),
                    cast(Pedido.numeroPedido, String).ilike(term),
                    func.coalesce(Pedido.codigoPedido, "").ilike(term),
                    Cliente.nombreCompleto.ilike(term),
                    Cliente.telefono.ilike(term),
                    Cliente.identificacion.ilike(term),
                    Entrega.destinatario.ilike(term),
                    Producto.nombreProducto.ilike(term),
                )
            )
        )

    total = db.query(func.count()).select_from(base.subquery()).scalar()

    ids_page = (
        base.distinct()
        .order_by(
            text("\"numeroOrdenFlag\""),
            text("\"ordenListado\" DESC"),
            Pedido.idPedido.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    pedido_ids = [int(row[0]) for row in ids_page]
    if not pedido_ids:
        return PedidoListResponse(items=[], total=total, page=page, pageSize=page_size)

    pedido_rows = (
        db.query(Pedido, Cliente, Entrega, EstadoPedido)
        .outerjoin(Cliente, Cliente.idCliente == Pedido.clienteID)
        .outerjoin(Entrega, Entrega.pedidoID == Pedido.idPedido)
        .outerjoin(EstadoPedido, EstadoPedido.idEstadoPedido == Pedido.estadoPedidoID)
        .filter(Pedido.idPedido.in_(pedido_ids))
        .all()
    )

    detalles_rows = (
        db.query(PedidoDetalle.pedidoID, Producto.nombreProducto)
        .outerjoin(Producto, Producto.idProducto == PedidoDetalle.productoID)
        .filter(PedidoDetalle.pedidoID.in_(pedido_ids))
        .all()
    )

    pagos_rows = db.execute(
        text(
            """
            SELECT pedido_id, metodo_pago
            FROM petalops.pago
            WHERE empresa_id = :empresa_id
              AND pedido_id = ANY(:pedido_ids)
            """
        ),
        {"empresa_id": int(empresa_id), "pedido_ids": pedido_ids},
    ).all()

    productos_por_pedido: dict[int, list[str]] = {}
    for pedido_id, nombre_producto in detalles_rows:
        productos_por_pedido.setdefault(int(pedido_id), []).append(str(nombre_producto or "Producto"))

    pago_por_pedido = {int(row[0]): (str(row[1]).strip() if row[1] is not None else None) for row in pagos_rows}

    rows_map = {int(pedido.idPedido): (pedido, cliente, entrega, estado_db) for pedido, cliente, entrega, estado_db in pedido_rows}

    items: list[PedidoListItem] = []
    for pedido_id in pedido_ids:
        pedido, cliente, entrega, estado_db = rows_map[pedido_id]
        estado_nombre = str((estado_db.nombreEstado if estado_db else "SIN_ESTADO") or "SIN_ESTADO")
        approval_gate = _approval_gate_summary(
            db,
            pedido_id=pedido_id,
            empresa_id=int(pedido.empresaID),
        )

        items.append(
            PedidoListItem(
                pedidoID=pedido_id,
                numeroPedido=_numero_pedido_valor(pedido, estado_nombre),
                codigoPedido=(
                    str(pedido.codigoPedido)
                    if pedido.codigoPedido and _estado_pedido_tiene_numeracion_visible(estado_nombre)
                    else None
                ),
                empresaID=int(pedido.empresaID),
                sucursalID=int(pedido.sucursalID),
                fecha=pedido.fechaPedido,
                fechaPedido=_fecha_pedido_str(pedido.fechaPedido),
                horaPedido=_hora_pedido_str(pedido.fechaPedido),
                cliente=str((cliente.nombreCompleto if cliente else None) or "Cliente"),
                destinatario=str((entrega.destinatario if entrega else None) or ""),
                fechaEntrega=_scheduled_entrega_datetime(entrega),
                horaEntrega=(entrega.rangoHora if entrega else None),
                productos=productos_por_pedido.get(pedido_id, []),
                total=float(pedido.totalNeto or 0),
                metodoPago=pago_por_pedido.get(pedido_id),
                canalFlora=approval_gate["pagoResumen"]["canalFlora"],
                puedeAprobar=approval_gate["puedeAprobar"],
                motivoBloqueoAprobacion=approval_gate["motivo"],
                estado=estado_nombre,
                telefono=str((cliente.telefono if cliente else None) or ""),
                telefonoCompleto=str(cliente.telefonoCompleto or "") if hasattr(cliente, "telefonoCompleto") else None,
            )
        )

    items.sort(
        key=lambda item: (
            0 if item.numeroPedido is None or int(item.numeroPedido or 0) <= 0 else 1,
            -(
                int(item.pedidoID or 0)
                if item.numeroPedido is None or int(item.numeroPedido or 0) <= 0
                else int(item.numeroPedido)
            ),
            -(int(item.pedidoID) if item.pedidoID is not None else 0),
        )
    )

    return PedidoListResponse(items=items, total=total, page=page, pageSize=page_size)


@router.get("/pedido/{pedido_id}/detalle", response_model=PedidoDetalleResponse, dependencies=[Depends(require_module_access("pedidos", "puedeVer"))])
def obtener_detalle_pedido(pedido_id: int, db: Session = Depends(get_db), auth=Depends(get_current_auth_context)):
    try:
        row_query = (
            db.query(Pedido, Cliente, EstadoPedido)
            .outerjoin(Cliente, Cliente.idCliente == Pedido.clienteID)
            .outerjoin(EstadoPedido, EstadoPedido.idEstadoPedido == Pedido.estadoPedidoID)
            .filter(Pedido.idPedido == pedido_id)
        )
        if not is_super_admin_context(auth):
            row_query = row_query.filter(Pedido.empresaID == int(auth.empresaID))
        row = row_query.first()

        if not row:
            pedido_logger.warning("Pedido no encontrado. pedido_id=%s", pedido_id)
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "PEDIDO_NOT_FOUND",
                    "message": "Pedido no encontrado",
                    "module": "pedido",
                },
            )

        pedido, cliente, estado_db = row
        estado_nombre = str((estado_db.nombreEstado if estado_db else "SIN_ESTADO") or "SIN_ESTADO")
        assert_same_empresa(auth, int(pedido.empresaID))

        entrega = (
            db.query(Entrega)
            .filter(Entrega.pedidoID == pedido.idPedido)
            .order_by(Entrega.intentoNumero.desc(), Entrega.idEntrega.desc())
            .first()
        )

        has_observaciones_personalizados = _pedido_detalle_has_observaciones_personalizados(db)

        detalles = (
            db.query(PedidoDetalle, Producto)
            .outerjoin(Producto, Producto.idProducto == PedidoDetalle.productoID)
            .filter(PedidoDetalle.pedidoID == pedido.idPedido)
            .all()
        )

        productos = [
            PedidoDetalleProducto(
                productoID=int(producto.idProducto),
                codigoProducto=(str(producto.codigoProducto).strip() if producto.codigoProducto else None),
                nombreProducto=str(producto.nombreProducto or "Producto"),
                cantidad=float(detalle.cantidad or 0),
                observaciones=_sanitize_producto_observacion(
                    (
                        str(getattr(detalle, "observacionesPersonalizados", "")).strip()
                        if has_observaciones_personalizados and getattr(detalle, "observacionesPersonalizados", None)
                        else None
                    ),
                    producto=producto,
                ),
                precioUnitario=float(detalle.precioUnitario or 0),
                subtotal=float(detalle.subtotal or 0),
            )
            for detalle, producto in detalles
        ]

        fecha_entrega_programada = _scheduled_entrega_datetime(entrega)
        pago_resumen = _load_pago_resumen(db, pedido_id=int(pedido.idPedido), empresa_id=int(pedido.empresaID))
        campos_empresa = _load_empresa_menu_rows(db, empresa_id=int(pedido.empresaID))

        return PedidoDetalleResponse(
            pedidoID=int(pedido.idPedido),
            numeroPedido=_numero_pedido_valor(pedido, estado_nombre),
            codigoPedido=(
                str(pedido.codigoPedido)
                if pedido.codigoPedido and _estado_pedido_tiene_numeracion_visible(estado_nombre)
                else None
            ),
            fecha=pedido.fechaPedido,
            fechaPedido=_fecha_pedido_str(pedido.fechaPedido),
            horaPedido=_hora_pedido_str(pedido.fechaPedido),
            estado=estado_nombre,
            empresaID=int(pedido.empresaID),
            sucursalID=int(pedido.sucursalID),
            motivoRechazo=pedido.motivoRechazo,
            cliente={
                "nombre": cliente.nombreCompleto,
                "telefono": cliente.telefono,
                "telefonoCompleto": getattr(cliente, "telefonoCompleto", None),
                "email": cliente.email,
                "identificacion": cliente.identificacion,
                "tipoIdent": getattr(cliente, "tipoIdent", None),
            },
            destinatario={
                "nombre": entrega.destinatario if entrega else None,
                "telefono": entrega.telefonoDestino if entrega else None,
                "direccion": entrega.direccion if entrega else None,
                "barrio": entrega.barrioNombre if entrega else None,
                "latitudDestino": (float(entrega.latitudDestino) if entrega and entrega.latitudDestino is not None else None),
                "longitudDestino": (float(entrega.longitudDestino) if entrega and entrega.longitudDestino is not None else None),
                "fechaEntrega": fecha_entrega_programada.isoformat() if fecha_entrega_programada else None,
                "horaEntrega": entrega.rangoHora if entrega else None,
                "firma": entrega.firma if entrega else None,
                "mensajeTarjeta": entrega.mensaje if entrega else None,
                "observacionGeneral": entrega.observacionGeneral if entrega else None,
            },
            financiero={
                "subtotal": float(pedido.totalBruto or 0),
                "iva": float(pedido.totalIva or 0),
                "domicilio": float(_pedido_domicilio_valor(pedido)),
                "total": float(pedido.totalNeto or 0),
                "estadoPago": None,
                "metodoPago": pago_resumen["metodoPago"],
                "metodosPago": pago_resumen["metodosPago"],
                "cuentaBancaria": pago_resumen["cuentaBancaria"],
                "canalFlora": pago_resumen["canalFlora"],
            },
            camposEmpresa={"pedidoDetalle": campos_empresa},
            productos=productos,
        )
    except HTTPException:
        raise
    except SQLAlchemyError:
        pedido_logger.error("Error SQL al obtener detalle de pedido. pedido_id=%s", pedido_id, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "PEDIDO_DB_ERROR",
                "message": "Error interno del servidor",
                "module": "pedido",
            },
        )
    except Exception:
        pedido_logger.error("Error inesperado al obtener detalle de pedido. pedido_id=%s", pedido_id, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "PEDIDO_INTERNAL_ERROR",
                "message": "Error interno del servidor",
                "module": "pedido",
            },
        )


class ActualizarDetallePedidoRequest(BaseModel):
    productoID: int | None = None
    productoPrecio: float | None = None
    cantidad: float | None = None
    productoObservaciones: str | None = None
    fechaEntrega: str | None = None   # ISO date "YYYY-MM-DD"
    horaEntrega: str | None = None    # Ej. "10:00 - 12:00"
    clienteTipoIdent: str | None = None
    clienteIdentificacion: str | None = None
    destinatarioNombre: str | None = None
    telefonoDestino: str | None = None
    direccion: str | None = None
    barrioNombre: str | None = None
    latitudDestino: float | None = None
    longitudDestino: float | None = None
    firma: str | None = None
    mensajeTarjeta: str | None = None
    observacionGeneral: str | None = None
    metodosPago: list[str] | None = None
    canalFlora: str | None = None


@router.put("/pedido/{pedido_id}/detalle", dependencies=[Depends(require_module_access("pedidos", "puedeEditar"))])
def actualizar_detalle_pedido(
    pedido_id: int,
    payload: ActualizarDetallePedidoRequest,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    try:
        empresa_id = int(auth.empresaID)
        has_observaciones_personalizados = _pedido_detalle_has_observaciones_personalizados(db)
        pedido = (
            db.query(Pedido)
            .filter(Pedido.idPedido == pedido_id, Pedido.empresaID == empresa_id)
            .first()
        )
        if not pedido:
            raise HTTPException(status_code=404, detail={"code": "PEDIDO_NOT_FOUND", "message": "Pedido no encontrado"})
        assert_same_empresa(auth, int(pedido.empresaID))
        if not _estado_pedido_editable(db, pedido.estadoPedidoID):
            raise HTTPException(
                status_code=409,
                detail={"code": "PEDIDO_NOT_EDITABLE", "message": "No se pueden editar pedidos entregados o cancelados"},
            )

        cliente = (
            db.query(Cliente)
            .filter(
                Cliente.idCliente == int(pedido.clienteID),
                Cliente.empresaID == int(pedido.empresaID),
            )
            .first()
        )
        if not cliente:
            raise HTTPException(status_code=404, detail={"code": "CLIENTE_NOT_FOUND", "message": "Cliente no encontrado"})

        detalle = (
            db.query(PedidoDetalle)
            .filter(
                PedidoDetalle.pedidoID == pedido_id,
                PedidoDetalle.empresaID == int(pedido.empresaID),
            )
            .order_by(PedidoDetalle.idPedidoDetalle.asc())
            .first()
        )
        needs_totals_recalc = False
        producto_detalle_actual: Producto | None = None

        if payload.productoID is not None and detalle and int(payload.productoID) != int(detalle.productoID):
            duplicate_detail = (
                db.query(PedidoDetalle.idPedidoDetalle)
                .filter(
                    PedidoDetalle.empresaID == int(pedido.empresaID),
                    PedidoDetalle.pedidoID == int(pedido.idPedido),
                    PedidoDetalle.productoID == int(payload.productoID),
                    PedidoDetalle.idPedidoDetalle != int(detalle.idPedidoDetalle),
                )
                .first()
            )
            if duplicate_detail:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": "PEDIDO_PRODUCTO_DUPLICADO",
                        "message": "Ese arreglo ya existe dentro del pedido. Elige otro arreglo diferente.",
                    },
                )
            precio_unitario = _find_branch_product_price(
                db,
                empresa_id=int(pedido.empresaID),
                sucursal_id=int(pedido.sucursalID),
                producto_id=int(payload.productoID),
            )
            producto = (
                db.query(Producto)
                .filter(
                    Producto.idProducto == int(payload.productoID),
                    Producto.empresaID == int(pedido.empresaID),
                )
                .first()
            )
            detalle.productoID = payload.productoID
            detalle.precioUnitario = precio_unitario
            producto_detalle_actual = producto
            if has_observaciones_personalizados:
                detalle.observacionesPersonalizados = _sanitize_producto_observacion(
                    payload.productoObservaciones,
                    producto=producto,
                )
            needs_totals_recalc = True
        elif payload.productoObservaciones is not None and detalle and has_observaciones_personalizados:
            producto_actual = (
                db.query(Producto)
                .filter(
                    Producto.idProducto == int(detalle.productoID),
                    Producto.empresaID == int(pedido.empresaID),
                )
                .first()
            )
            detalle.observacionesPersonalizados = _sanitize_producto_observacion(
                payload.productoObservaciones,
                producto=producto_actual,
            )

        if payload.productoPrecio is not None and detalle:
            producto_para_precio = producto_detalle_actual
            if producto_para_precio is None:
                producto_para_precio = (
                    db.query(Producto)
                    .filter(
                        Producto.idProducto == int(detalle.productoID),
                        Producto.empresaID == int(pedido.empresaID),
                    )
                    .first()
                )

            if not _is_custom_producto(producto_para_precio):
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": "PEDIDO_PRECIO_SOLO_PERSONALIZADO",
                        "message": "El precio solo se puede cambiar cuando el arreglo es personalizado.",
                    },
                )

            nuevo_precio = Decimal(str(payload.productoPrecio)).quantize(Decimal("1"))
            if nuevo_precio <= 0:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": "PEDIDO_PRECIO_INVALIDO",
                        "message": "Debes indicar un precio válido para el arreglo personalizado.",
                    },
                )

            detalle.precioUnitario = nuevo_precio
            needs_totals_recalc = True

        if payload.cantidad is not None and detalle:
            cantidad = Decimal(str(payload.cantidad))
            if cantidad <= 0:
                raise HTTPException(
                    status_code=400,
                    detail={"code": "PEDIDO_CANTIDAD_INVALIDA", "message": "La cantidad debe ser mayor que cero"},
                )
            detalle.cantidad = cantidad
            needs_totals_recalc = True

        if payload.clienteTipoIdent is not None:
            cliente.tipoIdent = _normalize_ident_type(payload.clienteTipoIdent)
            needs_totals_recalc = True
        if payload.clienteIdentificacion is not None:
            cliente.identificacion = str(payload.clienteIdentificacion).strip() or None

        if any(
            value is not None
            for value in (
                payload.fechaEntrega,
                payload.horaEntrega,
                payload.destinatarioNombre,
                payload.telefonoDestino,
                payload.direccion,
                payload.barrioNombre,
                payload.latitudDestino,
                payload.longitudDestino,
                payload.firma,
                payload.mensajeTarjeta,
                payload.observacionGeneral,
            )
        ):
            entrega = (
                db.query(Entrega)
                .filter(
                    Entrega.pedidoID == pedido_id,
                    Entrega.empresaID == int(pedido.empresaID),
                )
                .order_by(Entrega.intentoNumero.desc(), Entrega.idEntrega.desc())
                .first()
            )
            if entrega:
                if payload.fechaEntrega is not None:
                    entrega.fechaEntregaProgramada = _parse_iso_date(payload.fechaEntrega)
                if payload.horaEntrega is not None:
                    entrega.rangoHora = payload.horaEntrega or None
                if payload.destinatarioNombre is not None:
                    entrega.destinatario = str(payload.destinatarioNombre).strip() or None
                if payload.telefonoDestino is not None:
                    entrega.telefonoDestino = str(payload.telefonoDestino).strip() or None
                if payload.direccion is not None:
                    entrega.direccion = str(payload.direccion).strip() or None
                if payload.barrioNombre is not None:
                    entrega.barrioNombre = str(payload.barrioNombre).strip() or None
                    pedido.costoDomicilio = _resolve_costo_domicilio(
                        db,
                        empresa_id=int(pedido.empresaID),
                        sucursal_id=int(pedido.sucursalID),
                        tipo_entrega=getattr(entrega, "tipoEntrega", None),
                        barrio_id=(int(entrega.barrioID) if getattr(entrega, "barrioID", None) is not None else None),
                        barrio_nombre=entrega.barrioNombre,
                    )
                if payload.latitudDestino is not None:
                    entrega.latitudDestino = payload.latitudDestino
                if payload.longitudDestino is not None:
                    entrega.longitudDestino = payload.longitudDestino
                if payload.firma is not None:
                    entrega.firma = str(payload.firma).strip() or None
                if payload.mensajeTarjeta is not None:
                    entrega.mensaje = str(payload.mensajeTarjeta).strip() or None
                if payload.observacionGeneral is not None:
                    entrega.observacionGeneral = str(payload.observacionGeneral).strip() or None
                if payload.barrioNombre is not None:
                    pedido.totalNeto = (
                        Decimal(str(pedido.totalBruto or 0))
                        + Decimal(str(pedido.totalIva or 0))
                        + Decimal(str(getattr(pedido, "costoDomicilio", 0) or 0))
                    ).quantize(Decimal("0.01"))

                if payload.fechaEntrega is not None:
                    fecha_base = entrega.fechaEntregaProgramada or entrega.fechaEntrega
                    fecha_programada = produccion_service.calcular_fecha_programada(
                        fecha_entrega=fecha_base,
                        dias_anticipacion=_dias_anticipacion_produccion(),
                    )
                    producciones = (
                        db.query(Produccion)
                        .filter(
                            Produccion.pedidoID == pedido_id,
                            Produccion.empresaID == int(pedido.empresaID),
                        )
                        .all()
                    )
                    estado_cancelado_id = produccion_service.estado_produccion_id(db, produccion_service.ESTADO_CANCELADO)
                    for produccion in producciones:
                        if int(produccion.estado or 0) == int(estado_cancelado_id):
                            continue
                        produccion.fechaProgramadaProduccion = fecha_programada
                        produccion.updatedAt = datetime.now(timezone.utc)

        if needs_totals_recalc:
            _recalculate_pedido_financials(
                db,
                pedido=pedido,
                aplica_iva=_normalize_ident_type(cliente.tipoIdent) == "NIT",
            )

        if payload.metodosPago is not None or payload.canalFlora is not None:
            menu_config = _load_empresa_menu_config(db, empresa_id=int(pedido.empresaID))
            payment_field = menu_config.get("pedido_metodos_pago")
            channel_field = menu_config.get("pedido_canal_venta")
            metodos_pago = [str(item or "").strip() for item in (payload.metodosPago or []) if str(item or "").strip()]
            allowed_payment_methods = set(payment_field["opciones"]) if payment_field else set()
            invalid_payment_methods = [item for item in metodos_pago if allowed_payment_methods and item not in allowed_payment_methods]
            if invalid_payment_methods:
                raise HTTPException(
                    status_code=400,
                    detail={"code": "PAYMENT_METHOD_INVALID", "message": f"Métodos de pago inválidos: {', '.join(invalid_payment_methods)}"},
                )

            canal_flora = str(payload.canalFlora or "").strip() or None
            allowed_channels = set(channel_field["opciones"]) if channel_field else set()
            if channel_field and not canal_flora:
                raise HTTPException(
                    status_code=400,
                    detail={"code": "FLORA_CHANNEL_REQUIRED", "message": "Celular Flora es obligatorio"},
                )
            if canal_flora and allowed_channels and canal_flora not in allowed_channels:
                raise HTTPException(
                    status_code=400,
                    detail={"code": "FLORA_CHANNEL_INVALID", "message": "Canal de venta Flora inválido"},
                )

            monto_pago = Decimal(str(pedido.totalNeto or pedido.totalBruto or 0))
            _upsert_pago_flora(
                db,
                pedido_id=int(pedido.idPedido),
                empresa_id=int(pedido.empresaID),
                monto=monto_pago,
                metodos_pago=metodos_pago,
                canal_flora=canal_flora,
            )

        db.commit()
        return {"status": "ok", "pedidoID": pedido_id}
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        pedido_logger.error("Error SQL al actualizar detalle de pedido. pedido_id=%s", pedido_id, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "PEDIDO_UPDATE_DB_ERROR",
                "message": "Error interno del servidor",
                "module": "pedido",
            },
        )
    except Exception:
        db.rollback()
        pedido_logger.error("Error inesperado al actualizar detalle de pedido. pedido_id=%s", pedido_id, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "PEDIDO_UPDATE_INTERNAL_ERROR",
                "message": "Error interno del servidor",
                "module": "pedido",
            },
        )


@router.get("/pedido/{pedido_id}/factura", dependencies=[Depends(require_module_access("pedidos", "puedeVer"))])
def descargar_factura_pedido(pedido_id: int, db: Session = Depends(get_db), auth=Depends(get_current_auth_context)):
    row_query = (
        db.query(Pedido, Cliente, EstadoPedido)
        .outerjoin(Cliente, Cliente.idCliente == Pedido.clienteID)
        .outerjoin(EstadoPedido, EstadoPedido.idEstadoPedido == Pedido.estadoPedidoID)
        .filter(Pedido.idPedido == pedido_id)
    )
    if not is_super_admin_context(auth):
        row_query = row_query.filter(Pedido.empresaID == int(auth.empresaID))
    row = row_query.first()

    if not row:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")

    pedido, cliente, estado_db = row
    assert_same_empresa(auth, int(pedido.empresaID))
    estado_nombre = str((estado_db.nombreEstado if estado_db else "") or "")
    if not _estado_permite_factura(estado_nombre):
        raise HTTPException(status_code=400, detail="La factura solo est? disponible para pedidos APROBADO/PAGADO")

    entrega = (
        db.query(Entrega)
        .filter(
            Entrega.pedidoID == int(pedido.idPedido),
            Entrega.empresaID == int(pedido.empresaID),
        )
        .order_by(Entrega.intentoNumero.desc(), Entrega.idEntrega.desc())
        .first()
    )
    empresa = db.query(Empresa).filter(Empresa.idEmpresa == int(pedido.empresaID)).first()
    barrio = None
    if entrega and getattr(entrega, "barrioID", None) is not None:
        barrio = (
            db.query(Barrio)
            .filter(
                Barrio.idBarrio == int(entrega.barrioID),
                Barrio.empresaID == int(pedido.empresaID),
                Barrio.sucursalID == int(pedido.sucursalID),
            )
            .first()
        )
    pago_resumen = _load_pago_resumen(db, pedido_id=int(pedido.idPedido), empresa_id=int(pedido.empresaID))

    detalles = (
        db.query(PedidoDetalle, Producto)
        .outerjoin(Producto, Producto.idProducto == PedidoDetalle.productoID)
        .filter(PedidoDetalle.pedidoID == pedido.idPedido)
        .all()
    )

    lineas_productos = []
    observaciones_producto = []
    for detalle, producto in detalles:
        descripcion = str((producto.nombreProducto if producto else None) or "Producto").strip()
        cantidad = int(round(float(detalle.cantidad or 0)))
        lineas_productos.append(f"- {descripcion} | Cantidad: {cantidad}")
        observacion_detalle = str(getattr(detalle, "observacionesPersonalizados", "") or "").strip()
        if observacion_detalle:
            observaciones_producto.append(observacion_detalle)
    productos_texto = "\n".join(lineas_productos) if lineas_productos else "Sin productos"

    observaciones = " | ".join(observaciones_producto) or str((entrega.observacionGeneral if entrega else None) or "Sin observaciones")
    empresa_nombre = str(
        (getattr(empresa, "nombreComercial", None) or getattr(empresa, "nombreEmpresa", None) or "FLORA - TIENDA DE FLORES")
    ).strip()
    empresa_partes = [part.strip() for part in empresa_nombre.split(" - ", 1) if part.strip()]
    empresa_titulo = empresa_partes[0] if empresa_partes else empresa_nombre
    empresa_subtitulo = empresa_partes[1] if len(empresa_partes) > 1 else "Tienda de Flores"
    forma_pago = str(pago_resumen.get("metodoPago") or "No especificada").strip() or "No especificada"
    metodos_pago = [str(item or "").strip().lower() for item in (pago_resumen.get("metodosPago") or []) if str(item or "").strip()]
    if any("cuenta por cobrar" in item for item in metodos_pago):
        tipo_pago = "Cuentas Por Cobrar"
    elif any("transferencia" in item for item in metodos_pago):
        tipo_pago = "Transferencia"
    elif forma_pago != "No especificada":
        tipo_pago = forma_pago
    else:
        tipo_pago = "No especificada"

    fecha_entrega_programada = _scheduled_entrega_datetime(entrega)
    fecha_entrega_label = fecha_entrega_programada.strftime("%Y-%m-%d") if fecha_entrega_programada else "No especificada"
    zona_label = f"Zona {int(barrio.zonaID)}" if barrio and getattr(barrio, "zonaID", None) is not None else "Sin zona"
    operador_nombre = str(getattr(auth, "nombre", None) or getattr(auth, "login", None) or "-").strip() or "-"
    mensaje_final = str((entrega.mensaje if entrega else None) or "Gracias por su compra").strip() or "Gracias por su compra"
    numero_legible = str(pedido.numeroPedido) if int(pedido.numeroPedido or 0) > 0 else _numero_pedido_humano(pedido)
    celular_flora = str(pago_resumen.get("canalFlora") or "No especificada").strip() or "No especificada"

    contenido_lineas = [
        empresa_titulo.upper(),
        empresa_subtitulo,
        "----------------------------------------",
        f"Pedido: #{numero_legible}",
        f"Registro: {_fecha_hora_humano(pedido.fechaPedido)}",
        f"Entrega: {fecha_entrega_label}",
        "----------------------------------------",
        "CLIENTE",
        f"Nombre: {str((cliente.nombreCompleto if cliente else None) or '-')}",
        f"CC/NIT: {str((cliente.identificacion if cliente else None) or '-')}",
        f"Telefono: {str((cliente.telefonoCompleto if cliente else None) or (cliente.telefono if cliente else None) or '-')}",
        f"Pago: {forma_pago}",
        f"Tipo pago: {tipo_pago}",
        "----------------------------------------",
        "ENTREGA",
        f"Destinatario: {str((entrega.destinatario if entrega else None) or (cliente.nombreCompleto if cliente else None) or '-')}",
        f"Telefono: {str((entrega.telefonoDestino if entrega else None) or (cliente.telefonoCompleto if cliente else None) or (cliente.telefono if cliente else None) or '-')}",
        f"Barrio: {str((entrega.barrioNombre if entrega else None) or 'Recoger en Tienda')}",
        f"Zona: {zona_label}",
        "Direccion:",
        str((entrega.direccion if entrega else None) or "Recoger en Tienda"),
        "----------------------------------------",
        "PRODUCTOS",
        productos_texto,
        "----------------------------------------",
        "OBSERVACIONES",
        str(observaciones),
        "----------------------------------------",
        f"Subtotal: {_money_cop(pedido.totalBruto)}",
        f"Domicilio: {_money_cop(getattr(pedido, 'costoDomicilio', 0) or 0)}",
        f"Total: {_money_cop(pedido.totalNeto)}",
        "----------------------------------------",
        f"Operador: {operador_nombre}",
        f"Celular Flora: {celular_flora}",
        "",
        mensaje_final,
    ]

    pdf_bytes = _render_factura_pdf(contenido_lineas)
    headers = {
        "Content-Disposition": f"attachment; filename=factura_pedido_{pedido.idPedido}.pdf"
    }
    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)


@router.put("/pedido/{pedido_id}/aprobar", dependencies=[Depends(require_module_access("pedidos", "puedeEditar"))])
def aprobar_pedido(pedido_id: int, db: Session = Depends(get_db), auth=Depends(get_current_auth_context)):
    pedido_query = db.query(Pedido).filter(Pedido.idPedido == pedido_id)
    if not is_super_admin_context(auth):
        pedido_query = pedido_query.filter(Pedido.empresaID == int(auth.empresaID))
    try:
        pedido = pedido_query.with_for_update(nowait=True).first()
    except OperationalError as exc:
        db.rollback()
        if _is_lock_not_available_error(exc):
            raise HTTPException(
                status_code=409,
                detail="Otro usuario está aprobando este pedido en este momento. Intenta nuevamente en unos segundos.",
            ) from exc
        raise
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    assert_same_empresa(auth, int(pedido.empresaID))

    pendientes = _ids_estado_pendiente(db)
    if pendientes and int(pedido.estadoPedidoID) not in pendientes:
        estado_actual = _estado_pedido_nombre(db, pedido.estadoPedidoID)
        if estado_actual in {"APROBADO", "PAGADO"}:
            raise HTTPException(status_code=409, detail="Este pedido ya fue aprobado por otro usuario.")
        raise HTTPException(status_code=400, detail="Solo se pueden aprobar pedidos en estado Pendiente")

    approval_gate = _approval_gate_summary(
        db,
        pedido_id=int(pedido.idPedido),
        empresa_id=int(pedido.empresaID),
    )
    if not approval_gate["puedeAprobar"]:
        raise HTTPException(status_code=400, detail=approval_gate["motivo"])

    estado_aprobado = _buscar_estado_por_nombre(db, "APROBADO", "PAGADO")
    if not estado_aprobado:
        raise HTTPException(status_code=400, detail="No existe estado de aprobación activo (APROBADO/PAGADO)")

    if not _transicion_pedido_permitida(
        db=db,
        empresa_id=int(pedido.empresaID),
        origen_id=int(pedido.estadoPedidoID),
        destino_id=int(estado_aprobado.idEstadoPedido),
    ):
        raise HTTPException(status_code=400, detail="Transición de estado no permitida")

    if int(pedido.numeroPedido or 0) <= 0 or not str(pedido.codigoPedido or "").strip():
        numero_pedido, codigo_pedido = generar_numeracion_pedido(
            db=db,
            empresa_id=int(pedido.empresaID),
            sucursal_id=int(pedido.sucursalID),
        )
        pedido.numeroPedido = numero_pedido
        pedido.codigoPedido = codigo_pedido

    pedido.estadoPedidoID = estado_aprobado.idEstadoPedido
    pedido.motivoRechazo = None
    pedido.updatedAt = datetime.now(timezone.utc)

    produccion = asegurar_produccion_desde_pedido_aprobado_por_detalle(
        db=db,
        pedido=pedido,
        dias_anticipacion=_dias_anticipacion_produccion(),
        usuario="pedido.aprobar",
    )

    db.commit()

    return {
        "status": "ok",
        "pedidoID": pedido_id,
        "estado": str(estado_aprobado.nombreEstado),
        "notificaProduccion": True,
        "produccion": produccion,
    }


@router.put("/pedido/{pedido_id}/rechazar", dependencies=[Depends(require_module_access("pedidos", "puedeEditar"))])
def rechazar_pedido(pedido_id: int, payload: RechazarPedidoRequest, db: Session = Depends(get_db), auth=Depends(get_current_auth_context)):
    motivo = (payload.motivo or "").strip()
    if not motivo:
        raise HTTPException(status_code=400, detail="El motivo de rechazo es obligatorio")

    pedido_query = db.query(Pedido).filter(Pedido.idPedido == pedido_id)
    if not is_super_admin_context(auth):
        pedido_query = pedido_query.filter(Pedido.empresaID == int(auth.empresaID))
    try:
        pedido = pedido_query.with_for_update(nowait=True).first()
    except OperationalError as exc:
        db.rollback()
        if _is_lock_not_available_error(exc):
            raise HTTPException(
                status_code=409,
                detail="Otro usuario está actualizando este pedido en este momento. Intenta nuevamente en unos segundos.",
            ) from exc
        raise
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    assert_same_empresa(auth, int(pedido.empresaID))

    pendientes = _ids_estado_pendiente(db)
    if pendientes and int(pedido.estadoPedidoID) not in pendientes:
        raise HTTPException(status_code=400, detail="Solo se pueden rechazar pedidos en estado Pendiente")

    estado_rechazado = _buscar_estado_por_nombre(db, "RECHAZADO", "CANCELADO")
    if not estado_rechazado:
        raise HTTPException(status_code=400, detail="No existe estado de rechazo activo (RECHAZADO/CANCELADO)")

    pedido.estadoPedidoID = estado_rechazado.idEstadoPedido
    pedido.motivoRechazo = motivo[:300]
    pedido.updatedAt = datetime.now(timezone.utc)
    db.commit()

    return {
        "status": "ok",
        "pedidoID": pedido_id,
        "estado": str(estado_rechazado.nombreEstado),
        "motivo": pedido.motivoRechazo,
    }


@router.post("/pedido/checkout", response_model=PedidoCheckoutResponse, dependencies=[Depends(require_module_access("pedidos", "puedeCrear"))])
@limiter.limit("60/minute")
def checkout(request: Request, data: PedidoCheckoutRequest, db: Session = Depends(get_db), auth=Depends(get_current_auth_context)):
    """Endpoint de checkout: delega la lógica transaccional al servicio de pedidos."""
    assert_same_empresa(auth, int(data.empresaID))
    return checkout_pedido(db=db, payload=data)


@router.post("/pedido", dependencies=[Depends(require_module_access("pedidos", "puedeCrear"))])
@limiter.limit("60/minute")
def crear_pedido(request: Request, data: PedidoCreate, db: Session = Depends(get_db), auth=Depends(get_current_auth_context)):

    assert_same_empresa(auth, int(data.empresaId))

    try:
        estado_inicial = _buscar_estado_inicial_pedido(db)
        if not estado_inicial:
            raise HTTPException(status_code=400, detail="No existe un estado inicial activo 'CREADO' o 'PENDIENTE'")

        # 1️⃣ Validar productos
        productos_db = (
            db.query(Producto)
            .filter(
                Producto.idProducto.in_([i.productoId for i in data.items]),
                _activo_truthy(Producto.activo),
                Producto.empresaID == data.empresaId
            )
            .all()
        )

        if len(productos_db) != len(data.items):
            raise HTTPException(status_code=400, detail="Producto inválido")

        # 2️⃣ Calcular totales
        subtotal = Decimal("0.00")
        total_iva = Decimal("0.00")

        for item in data.items:
            producto = next(p for p in productos_db if p.idProducto == item.productoId)
            precio = _find_branch_product_price(
                db,
                empresa_id=int(data.empresaId),
                sucursal_id=int(data.sucursalId),
                producto_id=int(producto.idProducto),
            )
            linea = precio * Decimal(str(item.cantidad))
            subtotal += linea

        total = subtotal  # luego agregamos IVA real

        # 3️⃣ Crear cliente (simplificado)
        cliente = Cliente(
            empresaID=data.empresaId,
            tipoIdent="CC",
            identificacion=_cliente_identificacion_fallback(None, data.cliente.telefono),
            telefonoCompleto=data.cliente.telefono,
            nombreCompleto=data.cliente.nombres,
            telefono=data.cliente.telefono,
            email=data.cliente.email,
            activo=1,
            createdAt=datetime.now(timezone.utc),
        )

        db.add(cliente)
        db.flush()  # obtiene idCliente sin commit

        # 4️⃣ Crear pedido
        fecha_pedido = datetime.now(timezone.utc)

        pedido = Pedido(
            empresaID=data.empresaId,
            sucursalID=data.sucursalId,
            numeroPedido=_numero_pedido_temporal(),
            codigoPedido=None,
            clienteID=cliente.idCliente,
            fechaPedido=fecha_pedido,
            estadoPedidoID=int(estado_inicial.idEstadoPedido),
            totalBruto=subtotal.quantize(Decimal("0.01")),
            totalIva=total_iva.quantize(Decimal("0.01")),
            costoDomicilio=_resolve_costo_domicilio(
                db,
                empresa_id=int(data.empresaId),
                sucursal_id=int(data.sucursalId),
                tipo_entrega=data.entrega.tipoEntrega,
                barrio_id=data.entrega.barrioId,
                barrio_nombre=None,
            ),
            totalNeto=(
                total
                + _resolve_costo_domicilio(
                    db,
                    empresa_id=int(data.empresaId),
                    sucursal_id=int(data.sucursalId),
                    tipo_entrega=data.entrega.tipoEntrega,
                    barrio_id=data.entrega.barrioId,
                    barrio_nombre=None,
                )
            ).quantize(Decimal("0.01")),
            createdAt=datetime.now(timezone.utc),
        )

        db.add(pedido)
        db.flush()
        pedido.numeroPedido = -int(pedido.idPedido)

        # 5️⃣ Crear detalles
        for item in data.items:
            producto = next(p for p in productos_db if p.idProducto == item.productoId)
            precio_unitario = _find_branch_product_price(
                db,
                empresa_id=int(data.empresaId),
                sucursal_id=int(data.sucursalId),
                producto_id=int(producto.idProducto),
            )
            cantidad = Decimal(str(item.cantidad))

            detalle = PedidoDetalle(
                empresaID=data.empresaId,
                sucursalID=data.sucursalId,
                pedidoID=pedido.idPedido,
                productoID=producto.idProducto,
                cantidad=cantidad,
                precioUnitario=precio_unitario,
                ivaUnitario=Decimal("0.00"),
                totalLinea=(precio_unitario * cantidad).quantize(Decimal("0.01")),
                observacionesPersonalizados=None,
            )

            db.add(detalle)

        db.commit()

        return {
            "status": "ok",
            "idPedido": pedido.idPedido,
            "numeroPedido": (int(pedido.numeroPedido) if int(pedido.numeroPedido or 0) > 0 else None),
            "codigoPedido": (str(pedido.codigoPedido) if pedido.codigoPedido else None),
            "total": float(total.quantize(Decimal("0.01"))),
            "estado": str(estado_inicial.nombreEstado or "CREADO"),
        }

    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    
@router.put("/pedido/{pedido_id}/estado/{nuevo_estado_id}", dependencies=[Depends(require_module_access("pedidos", "puedeEditar"))])
def cambiar_estado(
    pedido_id: int,
    nuevo_estado_id: int,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    # 1️⃣ Buscar pedido
    pedido_query = db.query(Pedido).filter(Pedido.idPedido == pedido_id)
    if not is_super_admin_context(auth):
        pedido_query = pedido_query.filter(Pedido.empresaID == int(auth.empresaID))
    try:
        pedido = pedido_query.with_for_update(nowait=True).first()
    except OperationalError as exc:
        db.rollback()
        if _is_lock_not_available_error(exc):
            raise HTTPException(
                status_code=409,
                detail="Otro usuario está actualizando este pedido en este momento. Intenta nuevamente en unos segundos.",
            ) from exc
        raise

    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    assert_same_empresa(auth, int(pedido.empresaID))

    estado_actual = pedido.estadoPedidoID
    estado_actual_nombre = _estado_pedido_nombre(db, estado_actual)
    estado_destino_nombre = _estado_pedido_nombre(db, nuevo_estado_id)

    if estado_actual_nombre in {"APROBADO", "PAGADO"} and estado_destino_nombre in {"APROBADO", "PAGADO"}:
        raise HTTPException(status_code=409, detail="Este pedido ya fue aprobado por otro usuario.")

    # 2️⃣ Validar transición permitida
    if not _transicion_pedido_permitida(
        db=db,
        empresa_id=int(pedido.empresaID),
        origen_id=int(estado_actual),
        destino_id=int(nuevo_estado_id),
    ):
        raise HTTPException(
            status_code=400,
            detail="Transición de estado no permitida"
        )

    # 3️⃣ Actualizar estado
    pedido.estadoPedidoID = nuevo_estado_id
    pedido.updatedAt = datetime.now(timezone.utc)

    estado_destino = (
        db.query(EstadoPedido)
        .filter(
            EstadoPedido.idEstadoPedido == nuevo_estado_id,
            _activo_truthy(EstadoPedido.activo),
        )
        .first()
    )

    if not estado_destino:
        raise HTTPException(status_code=400, detail="Estado destino inválido o inactivo")

    produccion = None
    if str(estado_destino.nombreEstado or "").strip().upper() in {"APROBADO", "PAGADO"}:
        if int(pedido.numeroPedido or 0) <= 0 or not str(pedido.codigoPedido or "").strip():
            numero_pedido, codigo_pedido = generar_numeracion_pedido(
                db=db,
                empresa_id=int(pedido.empresaID),
                sucursal_id=int(pedido.sucursalID),
            )
            pedido.numeroPedido = numero_pedido
            pedido.codigoPedido = codigo_pedido
        approval_gate = _approval_gate_summary(
            db,
            pedido_id=int(pedido.idPedido),
            empresa_id=int(pedido.empresaID),
        )
        if not approval_gate["puedeAprobar"]:
            raise HTTPException(status_code=400, detail=approval_gate["motivo"])
        produccion = asegurar_produccion_desde_pedido_aprobado_por_detalle(
            db=db,
            pedido=pedido,
            dias_anticipacion=_dias_anticipacion_produccion(),
            usuario="pedido.cambiar_estado",
        )

    db.commit()

    return {"status": "ok", "nuevoEstado": nuevo_estado_id, "produccion": produccion}
