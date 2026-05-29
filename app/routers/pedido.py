import json
import os
import re
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy import and_, or_, cast, String, func, text
from datetime import date, datetime, timezone
from io import BytesIO
import textwrap
from reportlab.lib.units import mm
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
from app.models.sucursal import Sucursal

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
from app.core.security import (
    assert_same_empresa,
    get_current_auth_context,
    is_empresa_admin_context,
    is_super_admin_context,
    require_module_access,
)
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
    "RAPPI",
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
LINK_PAYMENT_METHODS = {"link bold", "link payu", "link wompi"}
LINK_SURCHARGE_PCT = Decimal("5.00")


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


def _catalog_code_from_name(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return normalized or "metodo_pago"


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


def _round_money_decimal(value: Decimal | int | float | None) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def _quantize_peso_entero(value: Decimal | int | float | None) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def _estado_permite_factura(value: str | None) -> bool:
    estado = str(value or "").strip().upper()
    return estado in {"APROBADO", "PAGADO"}


def _ticket_wrap_lines(raw_line: str, width: int) -> list[str]:
    value = str(raw_line or "")
    chunks: list[str] = []
    for paragraph in value.splitlines() or [""]:
        wrapped = textwrap.wrap(
            paragraph,
            width=width,
            break_long_words=False,
            break_on_hyphens=False,
            replace_whitespace=False,
            drop_whitespace=False,
        )
        if wrapped:
            chunks.extend(wrapped)
        else:
            chunks.append("")
    return chunks or [""]


def _render_factura_pdf(lines: list[str]) -> bytes:
    page_width = 80 * mm
    margin_x = 4 * mm
    font_size_title = 15
    font_size_subtitle = 10
    font_size_body = 10
    line_height = 13
    gap_after_block = 3
    max_chars = 40

    estimated_lines = 0
    normalized_blocks: list[list[str]] = []
    for raw_line in lines:
        wrapped_block = _ticket_wrap_lines(str(raw_line or ""), width=max_chars)
        normalized_blocks.append(wrapped_block)
        estimated_lines += len(wrapped_block) + 1

    content_height = max(estimated_lines * line_height + 28 * mm, 90 * mm)
    page_height = content_height

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(page_width, page_height))
    y = page_height - 6 * mm

    first_block = normalized_blocks[0] if normalized_blocks else []
    second_block = normalized_blocks[1] if len(normalized_blocks) > 1 else []

    if first_block:
        pdf.setFont("Helvetica-Bold", font_size_title)
        title = first_block[0].strip()
        pdf.drawCentredString(page_width / 2, y, title)
        y -= 16
    if second_block:
        pdf.setFont("Helvetica", font_size_subtitle)
        subtitle = second_block[0].strip()
        pdf.drawCentredString(page_width / 2, y, subtitle)
        y -= 16

    pdf.setFont("Helvetica", font_size_body)
    for wrapped_block in normalized_blocks[2:]:
        for line in wrapped_block:
            text_value = str(line or "")
            pdf.drawString(margin_x, y, text_value[: max_chars + 6])
            y -= line_height
        y -= gap_after_block

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


def _ensure_pedido_auditoria_table(db: Session):
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS petalops.pedido_auditoria (
              id_audit BIGSERIAL PRIMARY KEY,
              empresa_id BIGINT NOT NULL,
              sucursal_id BIGINT NOT NULL,
              pedido_id BIGINT NOT NULL,
              actor_user_id BIGINT,
              actor_login VARCHAR(120) NOT NULL,
              accion VARCHAR(60) NOT NULL,
              estado_origen_id BIGINT,
              estado_destino_id BIGINT,
              detalle_json TEXT,
              created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
    )
    db.execute(text("CREATE INDEX IF NOT EXISTS idx_pedido_auditoria_empresa_fecha ON petalops.pedido_auditoria (empresa_id, created_at DESC);"))
    db.execute(text("CREATE INDEX IF NOT EXISTS idx_pedido_auditoria_pedido ON petalops.pedido_auditoria (empresa_id, pedido_id);"))


def _audit_pedido_action(
    db: Session,
    actor,
    pedido: Pedido,
    accion: str,
    estado_origen_id: int | None,
    estado_destino_id: int | None,
    extra: dict | None = None,
):
    _ensure_pedido_auditoria_table(db)
    payload = json.dumps(extra or {}, ensure_ascii=True)
    db.execute(
        text(
            """
            INSERT INTO petalops.pedido_auditoria (
                empresa_id,
                sucursal_id,
                pedido_id,
                actor_user_id,
                actor_login,
                accion,
                estado_origen_id,
                estado_destino_id,
                detalle_json,
                created_at
            )
            VALUES (
                :empresa_id,
                :sucursal_id,
                :pedido_id,
                :actor_user_id,
                :actor_login,
                :accion,
                :estado_origen_id,
                :estado_destino_id,
                :detalle_json,
                CURRENT_TIMESTAMP
            )
            """
        ),
        {
            "empresa_id": int(pedido.empresaID),
            "sucursal_id": int(pedido.sucursalID),
            "pedido_id": int(pedido.idPedido),
            "actor_user_id": (int(getattr(actor, "userID", 0)) if getattr(actor, "userID", None) is not None else None),
            "actor_login": str(
                getattr(actor, "login", None)
                or getattr(actor, "nombre", None)
                or "system"
            ).strip() or "system",
            "accion": str(accion or "").strip() or "ACCION_PEDIDO",
            "estado_origen_id": (int(estado_origen_id) if estado_origen_id is not None else None),
            "estado_destino_id": (int(estado_destino_id) if estado_destino_id is not None else None),
            "detalle_json": payload,
        },
    )


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
    pago_resumen = _load_pago_resumen(db, pedido_id=int(pedido.idPedido), empresa_id=int(pedido.empresaID))
    ajustes = _build_pedido_adjustments(
        subtotal=Decimal(str(pedido.totalBruto or 0)),
        iva=Decimal(str(pedido.totalIva or 0)),
        domicilio=Decimal(str(getattr(pedido, "costoDomicilio", 0) or 0)),
        metodos_pago=list(pago_resumen.get("metodosPago") or []),
        omitir_recargo_link=bool(pago_resumen.get("omitirRecargoLink")),
        descuento_monto=Decimal(str(pago_resumen.get("descuentoMonto") or 0)),
        saldo_favor_monto=Decimal(str(pago_resumen.get("saldoFavorMonto") or 0)),
    )
    pedido.totalNeto = ajustes["total"]


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
        codigo = str(row["codigo"])
        opciones_normalizadas = [str(item) for item in opciones if str(item).strip()]
        if codigo == "pedido_metodos_pago" and "RAPPI" not in opciones_normalizadas:
            opciones_normalizadas.append("RAPPI")
        result.append(
            {
                "codigo": codigo,
                "titulo": str(row["titulo"]),
                "seccion": str(row["seccion"]),
                "tipoControl": str(row["tipo_control"]),
                "opciones": opciones_normalizadas,
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


def _normalize_delivery_type_from_barrio_name(barrio_nombre: str | None) -> str:
    nombre = str(barrio_nombre or "").strip().lower()
    return "recogida_en_tienda" if nombre == "recoger en tienda" else "domicilio"


def _find_barrio_by_name(db: Session, *, empresa_id: int, sucursal_id: int, barrio_nombre: str | None) -> Barrio | None:
    nombre = str(barrio_nombre or "").strip()
    if not nombre or nombre.lower() == "recoger en tienda":
        return None
    return (
        db.query(Barrio)
        .filter(
            Barrio.empresaID == int(empresa_id),
            Barrio.sucursalID == int(sucursal_id),
            func.lower(Barrio.nombreBarrio) == nombre.lower(),
        )
        .first()
    )


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


def _extract_payment_adjustments(raw_respuesta: str | None) -> dict:
    payload = _safe_parse_json(raw_respuesta)
    metadata = payload.get("_petalopsMetadata")
    if not isinstance(metadata, dict):
        metadata = {}

    omitir_recargo_link = bool(metadata.get("omitirRecargoLink", False))
    descuento_pct = float(metadata.get("descuentoPct") or 0)
    descuento_nota = str(metadata.get("descuentoNota") or "").strip() or None
    recargo_link_pct = float(metadata.get("recargoLinkPct") or 0)
    recargo_link_monto = float(metadata.get("recargoLinkMonto") or 0)
    descuento_monto = float(metadata.get("descuentoMonto") or 0)
    saldo_favor_monto = float(metadata.get("saldoFavorMonto") or 0)
    saldo_favor_nota = str(metadata.get("saldoFavorNota") or "").strip() or None
    factura_impresa = bool(metadata.get("facturaImpresa", False))
    factura_impresa_at = str(metadata.get("facturaImpresaAt") or "").strip() or None
    factura_impresa_by = str(metadata.get("facturaImpresaBy") or "").strip() or None

    return {
        "omitirRecargoLink": omitir_recargo_link,
        "descuentoPct": descuento_pct,
        "descuentoNota": descuento_nota,
        "recargoLinkPct": recargo_link_pct,
        "recargoLinkMonto": recargo_link_monto,
        "descuentoMonto": descuento_monto,
        "saldoFavorMonto": saldo_favor_monto,
        "saldoFavorNota": saldo_favor_nota,
        "facturaImpresa": factura_impresa,
        "facturaImpresaAt": factura_impresa_at,
        "facturaImpresaBy": factura_impresa_by,
    }


def _serialize_pago_metadata(
    raw_respuesta: str | None,
    *,
    canal_flora: str | None,
    omitir_recargo_link: bool | None = None,
    descuento_pct: Decimal | None = None,
    descuento_nota: str | None = None,
    recargo_link_pct: Decimal | None = None,
    recargo_link_monto: Decimal | None = None,
    descuento_monto: Decimal | None = None,
    saldo_favor_monto: Decimal | None = None,
    saldo_favor_nota: str | None = None,
    factura_impresa: bool | None = None,
    factura_impresa_at: str | None = None,
    factura_impresa_by: str | None = None,
) -> str | None:
    payload = _safe_parse_json(raw_respuesta)
    metadata = payload.get("_petalopsMetadata")
    if not isinstance(metadata, dict):
        metadata = {}

    cleaned_channel = str(canal_flora or "").strip()
    if cleaned_channel:
        metadata["canalFlora"] = cleaned_channel
    else:
        metadata.pop("canalFlora", None)

    if omitir_recargo_link is not None:
        metadata["omitirRecargoLink"] = bool(omitir_recargo_link)

    if descuento_pct is not None:
        pct_value = float(_round_money_decimal(descuento_pct))
        if pct_value > 0:
            metadata["descuentoPct"] = pct_value
        else:
            metadata.pop("descuentoPct", None)

    if descuento_nota is not None:
        cleaned_descuento_nota = str(descuento_nota or "").strip()
        if cleaned_descuento_nota:
            metadata["descuentoNota"] = cleaned_descuento_nota
        else:
            metadata.pop("descuentoNota", None)

    if recargo_link_pct is not None:
        pct_value = float(_round_money_decimal(recargo_link_pct))
        if pct_value > 0:
            metadata["recargoLinkPct"] = pct_value
        else:
            metadata.pop("recargoLinkPct", None)

    if recargo_link_monto is not None:
        amount_value = float(_round_money_decimal(recargo_link_monto))
        if amount_value > 0:
            metadata["recargoLinkMonto"] = amount_value
        else:
            metadata.pop("recargoLinkMonto", None)

    if descuento_monto is not None:
        amount_value = float(_round_money_decimal(descuento_monto))
        if amount_value > 0:
            metadata["descuentoMonto"] = amount_value
        else:
            metadata.pop("descuentoMonto", None)

    if saldo_favor_monto is not None:
        amount_value = float(_round_money_decimal(saldo_favor_monto))
        if amount_value > 0:
            metadata["saldoFavorMonto"] = amount_value
        else:
            metadata.pop("saldoFavorMonto", None)

    if saldo_favor_nota is not None:
        cleaned_saldo_favor_nota = str(saldo_favor_nota or "").strip()
        if cleaned_saldo_favor_nota:
            metadata["saldoFavorNota"] = cleaned_saldo_favor_nota
        else:
            metadata.pop("saldoFavorNota", None)

    if factura_impresa is not None:
        metadata["facturaImpresa"] = bool(factura_impresa)
        if not factura_impresa:
            metadata.pop("facturaImpresaAt", None)
            metadata.pop("facturaImpresaBy", None)

    if factura_impresa_at is not None:
        cleaned_factura_impresa_at = str(factura_impresa_at or "").strip()
        if cleaned_factura_impresa_at:
            metadata["facturaImpresaAt"] = cleaned_factura_impresa_at
        else:
            metadata.pop("facturaImpresaAt", None)

    if factura_impresa_by is not None:
        cleaned_factura_impresa_by = str(factura_impresa_by or "").strip()
        if cleaned_factura_impresa_by:
            metadata["facturaImpresaBy"] = cleaned_factura_impresa_by
        else:
            metadata.pop("facturaImpresaBy", None)

    if metadata:
        payload["_petalopsMetadata"] = metadata
    else:
        payload.pop("_petalopsMetadata", None)

    if not payload:
        return None
    return json.dumps(payload, ensure_ascii=False)


def _is_link_payment_method(method_name: str | None) -> bool:
    return str(method_name or "").strip().lower() in LINK_PAYMENT_METHODS


def _is_cash_payment_method(method_name: str | None) -> bool:
    normalized = str(method_name or "").strip().lower()
    return "efectivo" in normalized


def _build_pedido_adjustments(
    *,
    subtotal: Decimal,
    iva: Decimal,
    domicilio: Decimal,
    metodos_pago: list[str],
    omitir_recargo_link: bool,
    descuento_monto: Decimal,
    saldo_favor_monto: Decimal,
) -> dict:
    subtotal = _round_money_decimal(subtotal)
    iva = _round_money_decimal(iva)
    domicilio = _round_money_decimal(domicilio)
    base_total = _round_money_decimal(subtotal + iva + domicilio)
    has_link_payment = any(_is_link_payment_method(item) for item in (metodos_pago or []))

    recargo_link_pct = Decimal("0.00")
    recargo_link_monto = Decimal("0.00")
    if has_link_payment and not omitir_recargo_link:
        recargo_link_pct = LINK_SURCHARGE_PCT
        recargo_link_monto = _round_money_decimal((base_total * recargo_link_pct) / Decimal("100"))

    total_con_recargo = _round_money_decimal(base_total + recargo_link_monto)
    descuento_monto = _round_money_decimal(descuento_monto)
    saldo_favor_monto = _round_money_decimal(saldo_favor_monto)
    if descuento_monto < 0:
        descuento_monto = Decimal("0.00")
    if saldo_favor_monto < 0:
        saldo_favor_monto = Decimal("0.00")
    if descuento_monto > total_con_recargo:
        descuento_monto = total_con_recargo
    total_despues_descuento = _round_money_decimal(total_con_recargo - descuento_monto)
    if saldo_favor_monto > total_despues_descuento:
        saldo_favor_monto = total_despues_descuento
    total = _round_money_decimal(total_despues_descuento - saldo_favor_monto)

    return {
        "baseTotal": base_total,
        "hasLinkPayment": has_link_payment,
        "omitirRecargoLink": bool(omitir_recargo_link),
        "recargoLinkPct": recargo_link_pct,
        "recargoLinkMonto": recargo_link_monto,
        "descuentoPct": Decimal("0.00"),
        "descuentoMonto": descuento_monto,
        "saldoFavorMonto": saldo_favor_monto,
        "total": total,
    }


def _load_pago_resumen(db: Session, *, pedido_id: int, empresa_id: int) -> dict:
    pago_row = db.execute(
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
    ajustes = _extract_payment_adjustments(pago_row.get("raw_respuesta") if pago_row else None)

    if _flora_phase2_ready(db):
        metodos_rows = db.execute(
            text(
                """
                SELECT mpc.nombre, pm.monto
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
        detalle_pago = [
            {
                "metodo": str(row[0]).strip(),
                "monto": float(row[1] or 0),
            }
            for row in metodos_rows
            if row and row[0] is not None
        ]
        monto_efectivo = next(
            (
                float(item["monto"] or 0)
                for item in detalle_pago
                if _is_cash_payment_method(item["metodo"])
            ),
            None,
        )
        metodo_pago_legacy = str(pago_row.get("metodo_pago") or "").strip() if pago_row else ""
        metodos_pago_legacy = _parse_payment_methods(metodo_pago_legacy)
        if not metodos_pago and metodos_pago_legacy:
            metodos_pago = metodos_pago_legacy
        if metodos_pago or canal_row:
            metodo_pago = " | ".join(metodos_pago) if metodos_pago else (metodo_pago_legacy or None)
            if not detalle_pago and len(metodos_pago) == 1 and pago_row:
                detalle_pago = [{"metodo": metodos_pago[0], "monto": float(pago_row.get("monto") or 0)}]
            return {
                "metodoPago": metodo_pago,
                "metodosPago": metodos_pago,
                "detallePago": detalle_pago,
                "montoEfectivo": monto_efectivo,
                "cuentaBancaria": ", ".join([item for item in metodos_pago if item.startswith("Transferencia ")]) or None,
                "canalFlora": (str(canal_row[0]).strip() if canal_row and canal_row[0] is not None else None),
                **ajustes,
            }

    if not pago_row:
        return {
            "metodoPago": None,
            "metodosPago": [],
            "detallePago": [],
            "montoEfectivo": None,
            "cuentaBancaria": None,
            "canalFlora": None,
            **ajustes,
        }

    metodo_pago = str(pago_row.get("metodo_pago") or "").strip() or None
    metodos_pago = _parse_payment_methods(metodo_pago)
    monto_efectivo = (
        float(pago_row.get("monto") or 0)
        if any(_is_cash_payment_method(item) for item in metodos_pago)
        else None
    )
    return {
        "metodoPago": metodo_pago,
        "metodosPago": metodos_pago,
        "detallePago": [],
        "montoEfectivo": monto_efectivo,
        "cuentaBancaria": ", ".join([item for item in metodos_pago if item.startswith("Transferencia ")]) or None,
        "canalFlora": _extract_canal_flora(pago_row.get("raw_respuesta")),
        **ajustes,
    }


def _mark_factura_impresa(
    db: Session,
    *,
    pedido_id: int,
    empresa_id: int,
    actor_login: str | None,
) -> None:
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
    if not row:
        return

    raw_respuesta = _serialize_pago_metadata(
        row.get("raw_respuesta"),
        canal_flora=_extract_canal_flora(row.get("raw_respuesta")),
        factura_impresa=True,
        factura_impresa_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        factura_impresa_by=str(actor_login or "").strip() or None,
    )
    db.execute(
        text(
            """
            UPDATE petalops.pago
            SET raw_respuesta = :raw_respuesta,
                updated_at = NOW()
            WHERE id_pago = :id_pago
              AND empresa_id = :empresa_id
            """
        ),
        {
            "id_pago": int(row["id_pago"]),
            "empresa_id": int(empresa_id),
            "raw_respuesta": raw_respuesta,
        },
    )


def _load_pago_resumen_batch(db: Session, *, empresa_id: int, pedido_ids: list[int]) -> dict[int, dict]:
    if not pedido_ids:
        return {}

    pago_rows = db.execute(
        text(
            """
            SELECT pedido_id, metodo_pago, proveedor, referencia, raw_respuesta
            FROM petalops.pago
            WHERE empresa_id = :empresa_id
              AND pedido_id = ANY(:pedido_ids)
            """
        ),
        {"empresa_id": int(empresa_id), "pedido_ids": pedido_ids},
    ).mappings().all()
    pago_map = {int(row["pedido_id"]): row for row in pago_rows if row.get("pedido_id") is not None}

    phase2_rows: dict[int, list[dict]] = {}
    canales_map: dict[int, str | None] = {}
    if _flora_phase2_ready(db):
        metodos_rows = db.execute(
            text(
                """
                SELECT pm.pedido_id, mpc.nombre, pm.monto
                FROM petalops.pago_metodo pm
                JOIN petalops.metodo_pago_catalogo mpc
                  ON mpc.id_metodo_pago = pm.metodo_pago_id
                WHERE pm.empresa_id = :empresa_id
                  AND pm.pedido_id = ANY(:pedido_ids)
                ORDER BY pm.pedido_id ASC, pm.orden ASC, mpc.orden ASC, mpc.nombre ASC
                """
            ),
            {"empresa_id": int(empresa_id), "pedido_ids": pedido_ids},
        ).mappings().all()
        for row in metodos_rows:
            pedido_id = int(row["pedido_id"])
            phase2_rows.setdefault(pedido_id, []).append(
                {
                    "metodo": str(row["nombre"]).strip(),
                    "monto": float(row["monto"] or 0),
                }
            )

        canal_rows = db.execute(
            text(
                """
                SELECT pcv.pedido_id, cv.nombre
                FROM petalops.pedido_canal_venta pcv
                JOIN petalops.canal_venta cv
                  ON cv.id_canal_venta = pcv.canal_venta_id
                WHERE pcv.empresa_id = :empresa_id
                  AND pcv.pedido_id = ANY(:pedido_ids)
                """
            ),
            {"empresa_id": int(empresa_id), "pedido_ids": pedido_ids},
        ).mappings().all()
        canales_map = {
            int(row["pedido_id"]): (str(row["nombre"]).strip() if row.get("nombre") is not None else None)
            for row in canal_rows
            if row.get("pedido_id") is not None
        }

    result: dict[int, dict] = {}
    for pedido_id in pedido_ids:
        pago_row = pago_map.get(int(pedido_id))
        ajustes = _extract_payment_adjustments(pago_row.get("raw_respuesta") if pago_row else None)
        detalle_pago = phase2_rows.get(int(pedido_id), [])
        metodos_pago = [str(item["metodo"]).strip() for item in detalle_pago if str(item.get("metodo") or "").strip()]
        canal_flora = canales_map.get(int(pedido_id))
        metodo_pago_legacy = str(pago_row.get("metodo_pago") or "").strip() if pago_row else ""
        metodos_pago_legacy = _parse_payment_methods(metodo_pago_legacy)
        if not metodos_pago and metodos_pago_legacy:
            metodos_pago = metodos_pago_legacy
        if metodos_pago or canal_flora:
            metodo_pago = " | ".join(metodos_pago) if metodos_pago else None
            monto_efectivo = next(
                (float(item["monto"] or 0) for item in detalle_pago if _is_cash_payment_method(item["metodo"])),
                None,
            )
            if not detalle_pago and len(metodos_pago) == 1 and pago_row:
                detalle_pago = [{"metodo": metodos_pago[0], "monto": float(pago_row.get("monto") or 0)}]
            result[int(pedido_id)] = {
                "metodoPago": metodo_pago,
                "metodosPago": metodos_pago,
                "detallePago": detalle_pago,
                "montoEfectivo": monto_efectivo,
                "cuentaBancaria": ", ".join([item for item in metodos_pago if item.startswith("Transferencia ")]) or None,
                "canalFlora": canal_flora,
                **ajustes,
            }
            continue

        if not pago_row:
            result[int(pedido_id)] = {
                "metodoPago": None,
                "metodosPago": [],
                "detallePago": [],
                "montoEfectivo": None,
                "cuentaBancaria": None,
                "canalFlora": None,
                **ajustes,
            }
            continue

        metodo_pago = str(pago_row.get("metodo_pago") or "").strip() or None
        metodos_pago = _parse_payment_methods(metodo_pago)
        result[int(pedido_id)] = {
            "metodoPago": metodo_pago,
            "metodosPago": metodos_pago,
            "detallePago": [],
            "montoEfectivo": None,
            "cuentaBancaria": ", ".join([item for item in metodos_pago if item.startswith("Transferencia ")]) or None,
            "canalFlora": _extract_canal_flora(pago_row.get("raw_respuesta")),
            **ajustes,
        }
    return result


def _approval_gate_summary(db: Session, *, pedido_id: int, empresa_id: int) -> dict:
    rules = _tenant_order_rules(db, int(empresa_id))
    pago_resumen = _load_pago_resumen(db, pedido_id=int(pedido_id), empresa_id=int(empresa_id))

    missing = []
    if rules["require_payment_before_approval"] and not pago_resumen["metodosPago"]:
        missing.append("método de pago")
    if rules["require_sales_channel_before_approval"] and not pago_resumen["canalFlora"]:
        missing.append("medio de venta")

    metodos_pago = [str(item or "").strip() for item in (pago_resumen.get("metodosPago") or []) if str(item or "").strip()]
    detalle_pago = pago_resumen.get("detallePago") or []
    if len(metodos_pago) > 1:
        if not detalle_pago or len(detalle_pago) < len(metodos_pago):
            missing.append("monto por cada método de pago")
        else:
            total_detalle = Decimal("0.00")
            metodos_con_monto = set()
            for item in detalle_pago:
                metodo = str(item.get("metodo") or item.get("metodoPago") or "").strip()
                monto = Decimal(str(item.get("monto") or item.get("valor") or item.get("amount") or 0))
                if metodo and monto > 0:
                    metodos_con_monto.add(metodo)
                    total_detalle += monto
            if any(metodo not in metodos_con_monto for metodo in metodos_pago):
                missing.append("monto por cada método de pago")
            total_pedido = _round_money_decimal(db.query(Pedido.totalNeto).filter(Pedido.idPedido == int(pedido_id), Pedido.empresaID == int(empresa_id)).scalar() or 0)
            if _round_money_decimal(total_detalle) != total_pedido:
                missing.append("distribución correcta de los montos de pago")

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
    detalle_pago: list[dict] | None = None,
    monto_efectivo: Decimal | None = None,
    omitir_recargo_link: bool = False,
    descuento_pct: Decimal | None = None,
    descuento_nota: str | None = None,
    recargo_link_pct: Decimal | None = None,
    recargo_link_monto: Decimal | None = None,
    descuento_monto: Decimal | None = None,
    saldo_favor_monto: Decimal | None = None,
    saldo_favor_nota: str | None = None,
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
    raw_respuesta = _serialize_pago_metadata(
        row.get("raw_respuesta") if row else None,
        canal_flora=canal_flora,
        omitir_recargo_link=omitir_recargo_link,
        descuento_pct=descuento_pct,
        descuento_nota=descuento_nota,
        recargo_link_pct=recargo_link_pct,
        recargo_link_monto=recargo_link_monto,
        descuento_monto=descuento_monto,
        saldo_favor_monto=saldo_favor_monto,
        saldo_favor_nota=saldo_favor_nota,
    )

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
                  AND lower(nombre) = ANY(:names)
                """
            ),
            {"empresa_id": int(empresa_id), "names": [str(item or "").strip().lower() for item in metodos_pago]},
        ).mappings().all()
        metodo_by_name = {str(row["nombre"]).strip().lower(): int(row["id_metodo_pago"]) for row in metodo_catalog_rows}
    else:
        metodo_by_name = {}

    missing_methods = [
        metodo
        for metodo in metodos_pago
        if str(metodo or "").strip() and str(metodo or "").strip().lower() not in metodo_by_name
    ]
    for metodo in missing_methods:
        next_order_row = db.execute(
            text(
                """
                SELECT COALESCE(MAX(orden), 0) + 1
                FROM petalops.metodo_pago_catalogo
                WHERE empresa_id = :empresa_id
                """
            ),
            {"empresa_id": int(empresa_id)},
        ).first()
        next_order = int(next_order_row[0] or 1) if next_order_row else 1
        inserted = db.execute(
            text(
                """
                INSERT INTO petalops.metodo_pago_catalogo (
                    empresa_id,
                    codigo,
                    nombre,
                    orden,
                    activo,
                    created_at,
                    updated_at
                ) VALUES (
                    :empresa_id,
                    :codigo,
                    :nombre,
                    :orden,
                    TRUE,
                    NOW(),
                    NOW()
                )
                RETURNING id_metodo_pago
                """
            ),
            {
                "empresa_id": int(empresa_id),
                "codigo": _catalog_code_from_name(metodo),
                "nombre": str(metodo).strip(),
                "orden": next_order,
            },
        ).first()
        if inserted and inserted[0] is not None:
            metodo_by_name[str(metodo).strip().lower()] = int(inserted[0])

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

    breakdown_by_method = {}
    if isinstance(detalle_pago, list):
        for item in detalle_pago:
            if not isinstance(item, dict):
                continue
            metodo_nombre = str(item.get("metodo") or item.get("metodoPago") or "").strip()
            if not metodo_nombre:
                continue
            breakdown_by_method[metodo_nombre] = _round_money_decimal(item.get("monto") or item.get("valor") or item.get("amount") or 0)
    elif len(metodos_pago) == 1:
        breakdown_by_method[metodos_pago[0]] = _round_money_decimal(monto)

    for index, metodo in enumerate(metodos_pago, start=1):
        metodo_id = metodo_by_name.get(str(metodo).strip().lower())
        if metodo_id is None:
            continue
        monto_metodo = breakdown_by_method.get(metodo)
        if monto_metodo is None:
            if len(metodos_pago) == 1:
                monto_metodo = _round_money_decimal(monto)
            elif _is_cash_payment_method(metodo) and monto_efectivo is not None:
                monto_metodo = _round_money_decimal(monto_efectivo)
            else:
                monto_metodo = Decimal("0.00")
        db.execute(
            text(
                """
                INSERT INTO petalops.pago_metodo (
                    empresa_id,
                    pago_id,
                    pedido_id,
                    metodo_pago_id,
                    monto,
                    orden,
                    created_at,
                    updated_at
                ) VALUES (
                    :empresa_id,
                    :pago_id,
                    :pedido_id,
                    :metodo_pago_id,
                    :monto,
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
                "monto": monto_metodo,
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
                  AND lower(nombre) = lower(:nombre)
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


def _sync_existing_pago_total(db: Session, *, pedido: Pedido) -> None:
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
        {
            "pedido_id": int(pedido.idPedido),
            "empresa_id": int(pedido.empresaID),
        },
    ).first()
    if not pago_row:
        return

    monto = Decimal(str(pedido.totalNeto or pedido.totalBruto or 0))
    db.execute(
        text(
            """
            UPDATE petalops.pago
            SET monto = :monto,
                updated_at = NOW()
            WHERE id_pago = :id_pago
              AND empresa_id = :empresa_id
            """
        ),
        {
            "id_pago": int(pago_row[0]),
            "empresa_id": int(pedido.empresaID),
            "monto": monto,
        },
    )

    if not _flora_phase2_ready(db):
        return

    pago_resumen = _load_pago_resumen(db, pedido_id=int(pedido.idPedido), empresa_id=int(pedido.empresaID))
    metodos_pago = list(pago_resumen.get("metodosPago") or [])
    if len(metodos_pago) != 1:
        return

    metodo_row = db.execute(
        text(
            """
            SELECT pm.id_pago_metodo
            FROM petalops.pago_metodo pm
            JOIN petalops.metodo_pago_catalogo mpc
              ON mpc.id_metodo_pago = pm.metodo_pago_id
            WHERE pm.empresa_id = :empresa_id
              AND pm.pedido_id = :pedido_id
              AND mpc.nombre = :metodo
            LIMIT 1
            """
        ),
        {
            "empresa_id": int(pedido.empresaID),
            "pedido_id": int(pedido.idPedido),
            "metodo": str(metodos_pago[0]),
        },
    ).first()
    if not metodo_row:
        return

    db.execute(
        text(
            """
            UPDATE petalops.pago_metodo
            SET monto = :monto,
                updated_at = NOW()
            WHERE id_pago_metodo = :id_pago_metodo
              AND empresa_id = :empresa_id
            """
        ),
        {
            "id_pago_metodo": int(metodo_row[0]),
            "empresa_id": int(pedido.empresaID),
            "monto": monto,
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
    sin_imprimir: bool = Query(False, alias="sinImprimir"),
    solo_tienda: bool = Query(False, alias="soloTienda"),
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
        .outerjoin(
            Cliente,
            and_(
                Cliente.idCliente == Pedido.clienteID,
                Cliente.empresaID == Pedido.empresaID,
            ),
        )
        .outerjoin(
            Entrega,
            and_(
                Entrega.pedidoID == Pedido.idPedido,
                Entrega.empresaID == Pedido.empresaID,
            ),
        )
        .outerjoin(EstadoPedido, EstadoPedido.idEstadoPedido == Pedido.estadoPedidoID)
        .filter(Pedido.empresaID == empresa_id)
    )

    if sucursal_id is not None:
        base = base.filter(Pedido.sucursalID == sucursal_id)

    has_search = bool(str(q or "").strip())

    if estado and not has_search:
        base = base.filter(func.upper(EstadoPedido.nombreEstado) == estado.upper())

    if fecha_desde and not has_search:
        base = base.filter(Pedido.fechaPedido >= fecha_desde)

    if fecha_hasta and not has_search:
        base = base.filter(Pedido.fechaPedido <= fecha_hasta)

    if solo_tienda:
        base = base.filter(
            or_(
                func.lower(func.coalesce(Entrega.tipoEntrega, "")).in_(("recogida_en_tienda", "tienda")),
                func.lower(func.coalesce(Entrega.barrioNombre, "")).ilike("%tienda%"),
            )
        )

    if has_search:
        term = f"%{q.strip()}%"
        payment_and_channel_search = text(
            """
            (
                EXISTS (
                    SELECT 1
                    FROM petalops.pago p
                    LEFT JOIN petalops.pago_metodo pm
                      ON pm.pago_id = p.id_pago
                     AND pm.empresa_id = p.empresa_id
                    LEFT JOIN petalops.metodo_pago_catalogo mpc
                      ON mpc.id_metodo_pago = pm.metodo_pago_id
                     AND mpc.empresa_id = p.empresa_id
                    WHERE p.empresa_id = petalops.pedido.empresa_id
                      AND p.pedido_id = petalops.pedido.id_pedido
                      AND (
                          COALESCE(p.metodo_pago, '') ILIKE :search_term
                          OR COALESCE(p.proveedor, '') ILIKE :search_term
                          OR COALESCE(p.referencia, '') ILIKE :search_term
                          OR COALESCE(mpc.nombre, '') ILIKE :search_term
                      )
                )
                OR EXISTS (
                    SELECT 1
                    FROM petalops.pedido_canal_venta pcv
                    JOIN petalops.canal_venta cv
                      ON cv.id_canal_venta = pcv.canal_venta_id
                     AND cv.empresa_id = pcv.empresa_id
                    WHERE pcv.empresa_id = petalops.pedido.empresa_id
                      AND pcv.pedido_id = petalops.pedido.id_pedido
                      AND COALESCE(cv.nombre, '') ILIKE :search_term
                )
            )
            """
        ).bindparams(search_term=term)
        base = (
            base.outerjoin(
                PedidoDetalle,
                and_(
                    PedidoDetalle.pedidoID == Pedido.idPedido,
                    PedidoDetalle.empresaID == Pedido.empresaID,
                ),
            )
            .outerjoin(
                Producto,
                and_(
                    Producto.idProducto == PedidoDetalle.productoID,
                    Producto.empresaID == Pedido.empresaID,
                ),
            )
            .outerjoin(
                Sucursal,
                and_(
                    Sucursal.idSucursal == Pedido.sucursalID,
                    Sucursal.empresaID == Pedido.empresaID,
                ),
            )
            .filter(
                or_(
                    cast(Pedido.idPedido, String).ilike(term),
                    cast(Pedido.numeroPedido, String).ilike(term),
                    func.coalesce(Pedido.codigoPedido, "").ilike(term),
                    func.coalesce(Cliente.nombreCompleto, "").ilike(term),
                    func.coalesce(Cliente.telefono, "").ilike(term),
                    func.coalesce(Cliente.telefonoCompleto, "").ilike(term),
                    func.coalesce(Cliente.identificacion, "").ilike(term),
                    func.coalesce(Entrega.destinatario, "").ilike(term),
                    func.coalesce(Entrega.telefonoDestino, "").ilike(term),
                    func.coalesce(Entrega.direccion, "").ilike(term),
                    func.coalesce(Entrega.barrioNombre, "").ilike(term),
                    func.coalesce(Entrega.mensaje, "").ilike(term),
                    func.coalesce(Entrega.firma, "").ilike(term),
                    func.coalesce(Entrega.firmaNombre, "").ilike(term),
                    func.coalesce(Entrega.observacionGeneral, "").ilike(term),
                    func.coalesce(Entrega.observaciones, "").ilike(term),
                    func.coalesce(PedidoDetalle.observacionesPersonalizados, "").ilike(term),
                    func.coalesce(Producto.nombreProducto, "").ilike(term),
                    func.coalesce(Sucursal.telefono, "").ilike(term),
                    payment_and_channel_search,
                )
            )
        )

    candidate_rows = (
        base.distinct()
        .order_by(
            text("\"numeroOrdenFlag\""),
            text("\"ordenListado\" DESC"),
            Pedido.idPedido.desc(),
        )
        .all()
    )
    candidate_ids = [int(row[0]) for row in candidate_rows]
    if not candidate_ids:
        return PedidoListResponse(items=[], total=0, page=page, pageSize=page_size, facturasPendientesImpresion=0)

    estado_rows = (
        db.query(Pedido.idPedido, EstadoPedido.nombreEstado)
        .outerjoin(EstadoPedido, EstadoPedido.idEstadoPedido == Pedido.estadoPedidoID)
        .filter(Pedido.empresaID == int(empresa_id), Pedido.idPedido.in_(candidate_ids))
        .all()
    )
    estado_map = {
        int(pedido_id): str(nombre_estado or "SIN_ESTADO")
        for pedido_id, nombre_estado in estado_rows
    }
    pago_resumen_map = _load_pago_resumen_batch(db, empresa_id=int(empresa_id), pedido_ids=candidate_ids)
    pending_invoice_ids = [
        int(pedido_id)
        for pedido_id in candidate_ids
        if _estado_permite_factura(estado_map.get(int(pedido_id)))
        and not bool((pago_resumen_map.get(int(pedido_id)) or {}).get("facturaImpresa"))
    ]
    facturas_pendientes_impresion = len(pending_invoice_ids)
    filtered_ids = pending_invoice_ids if sin_imprimir else candidate_ids
    total = len(filtered_ids)

    pedido_ids = filtered_ids[(page - 1) * page_size : ((page - 1) * page_size) + page_size]
    if not pedido_ids:
        return PedidoListResponse(
            items=[],
            total=total,
            page=page,
            pageSize=page_size,
            facturasPendientesImpresion=facturas_pendientes_impresion,
        )

    pago_resumen_page = {int(pedido_id): pago_resumen_map.get(int(pedido_id), {}) for pedido_id in pedido_ids}

    pedido_rows = (
        db.query(Pedido, Cliente, Entrega, EstadoPedido)
        .outerjoin(
            Cliente,
            and_(
                Cliente.idCliente == Pedido.clienteID,
                Cliente.empresaID == Pedido.empresaID,
            ),
        )
        .outerjoin(
            Entrega,
            and_(
                Entrega.pedidoID == Pedido.idPedido,
                Entrega.empresaID == Pedido.empresaID,
            ),
        )
        .outerjoin(EstadoPedido, EstadoPedido.idEstadoPedido == Pedido.estadoPedidoID)
        .filter(Pedido.empresaID == int(empresa_id), Pedido.idPedido.in_(pedido_ids))
        .all()
    )

    detalles_rows = (
        db.query(PedidoDetalle.pedidoID, Producto.nombreProducto)
        .outerjoin(
            Producto,
            and_(
                Producto.idProducto == PedidoDetalle.productoID,
                Producto.empresaID == PedidoDetalle.empresaID,
            ),
        )
        .filter(PedidoDetalle.empresaID == int(empresa_id), PedidoDetalle.pedidoID.in_(pedido_ids))
        .all()
    )

    productos_por_pedido: dict[int, list[str]] = {}
    for pedido_id, nombre_producto in detalles_rows:
        productos_por_pedido.setdefault(int(pedido_id), []).append(str(nombre_producto or "Producto"))

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
                tipoEntrega=str((entrega.tipoEntrega if entrega else None) or ""),
                direccionEntrega=str((entrega.direccion if entrega else None) or ""),
                barrioNombre=str((entrega.barrioNombre if entrega else None) or ""),
                fechaEntrega=_scheduled_entrega_datetime(entrega),
                horaEntrega=(entrega.rangoHora if entrega else None),
                productos=productos_por_pedido.get(pedido_id, []),
                total=float(pedido.totalNeto or 0),
                metodoPago=(pago_resumen_page.get(pedido_id) or approval_gate["pagoResumen"]).get("metodoPago"),
                canalFlora=(pago_resumen_page.get(pedido_id) or approval_gate["pagoResumen"]).get("canalFlora"),
                puedeAprobar=approval_gate["puedeAprobar"],
                motivoBloqueoAprobacion=approval_gate["motivo"],
                estado=estado_nombre,
                motivoRechazo=pedido.motivoRechazo,
                telefono=str((cliente.telefono if cliente else None) or ""),
                telefonoCompleto=str(cliente.telefonoCompleto or "") if hasattr(cliente, "telefonoCompleto") else None,
                facturaImpresa=bool((pago_resumen_page.get(pedido_id) or {}).get("facturaImpresa")),
                facturaImpresaAt=(pago_resumen_page.get(pedido_id) or {}).get("facturaImpresaAt"),
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

    return PedidoListResponse(
        items=items,
        total=total,
        page=page,
        pageSize=page_size,
        facturasPendientesImpresion=facturas_pendientes_impresion,
    )


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
                detalleID=int(detalle.idPedidoDetalle),
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
                precioUnitario=float(_quantize_peso_entero(detalle.precioUnitario or 0)),
                subtotal=float(_quantize_peso_entero(detalle.subtotal or 0)),
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
                "detallePago": pago_resumen.get("detallePago") or [],
                "montoEfectivo": pago_resumen.get("montoEfectivo"),
                "cuentaBancaria": pago_resumen["cuentaBancaria"],
                "canalFlora": pago_resumen["canalFlora"],
                "omitirRecargoLink": bool(pago_resumen.get("omitirRecargoLink")),
                "descuentoPct": float(pago_resumen.get("descuentoPct") or 0),
                "recargoLinkPct": float(pago_resumen.get("recargoLinkPct") or 0),
                "recargoLinkMonto": float(pago_resumen.get("recargoLinkMonto") or 0),
                "descuentoMonto": float(pago_resumen.get("descuentoMonto") or 0),
                "descuentoNota": pago_resumen.get("descuentoNota"),
                "saldoFavorMonto": float(pago_resumen.get("saldoFavorMonto") or 0),
                "saldoFavorNota": pago_resumen.get("saldoFavorNota"),
                "facturaImpresa": bool(pago_resumen.get("facturaImpresa")),
                "facturaImpresaAt": pago_resumen.get("facturaImpresaAt"),
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
    detalleID: int | None = None
    productoID: int | None = None
    productoPrecio: float | None = None
    cantidad: float | None = None
    productoObservaciones: str | None = None
    fechaEntrega: str | None = None   # ISO date "YYYY-MM-DD"
    horaEntrega: str | None = None    # Ej. "10:00 - 12:00"
    clienteNombre: str | None = None
    clienteTelefono: str | None = None
    clienteEmail: str | None = None
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
    detallePago: list[dict] | None = None
    montoEfectivo: float | None = None
    omitirRecargoLink: bool | None = None
    descuentoMonto: float | None = None
    descuentoNota: str | None = None
    saldoFavorMonto: float | None = None
    saldoFavorNota: str | None = None
    canalFlora: str | None = None


class AgregarDetallePedidoRequest(BaseModel):
    productoID: int
    cantidad: float | None = 1
    productoObservaciones: str | None = None
    productoPrecio: float | None = None


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

        detalle_query = (
            db.query(PedidoDetalle)
            .filter(
                PedidoDetalle.pedidoID == pedido_id,
                PedidoDetalle.empresaID == int(pedido.empresaID),
            )
        )
        detalle = None
        if payload.detalleID is not None:
            detalle = (
                detalle_query
                .filter(PedidoDetalle.idPedidoDetalle == int(payload.detalleID))
                .first()
            )
            if not detalle:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "code": "PEDIDO_DETALLE_NOT_FOUND",
                        "message": "No fue posible ubicar el arreglo seleccionado dentro del pedido.",
                    },
                )
        elif payload.productoID is not None:
            detalle = (
                detalle_query
                .filter(PedidoDetalle.productoID == int(payload.productoID))
                .order_by(PedidoDetalle.idPedidoDetalle.asc())
                .first()
            )
        if not detalle:
            detalle = detalle_query.order_by(PedidoDetalle.idPedidoDetalle.asc()).first()
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

            nuevo_precio = _quantize_peso_entero(payload.productoPrecio)
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

        if any(value is not None for value in (payload.clienteNombre, payload.clienteTelefono)):
            if not (is_empresa_admin_context(auth) or is_super_admin_context(auth)):
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": "PEDIDO_CLIENT_EDIT_FORBIDDEN",
                        "message": "Solo un usuario administrador puede editar nombre o teléfono del cliente.",
                    },
                )

        if payload.clienteNombre is not None:
            cliente.nombreCompleto = str(payload.clienteNombre).strip() or cliente.nombreCompleto
        if payload.clienteTelefono is not None:
            telefono_cliente = str(payload.clienteTelefono).strip()
            cliente.telefono = telefono_cliente or None
            if hasattr(cliente, "telefonoCompleto"):
                cliente.telefonoCompleto = telefono_cliente or None
        if payload.clienteEmail is not None:
            cliente.email = str(payload.clienteEmail).strip().lower() or None
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
                    entrega.tipoEntrega = _normalize_delivery_type_from_barrio_name(entrega.barrioNombre)
                    barrio_actualizado = _find_barrio_by_name(
                        db,
                        empresa_id=int(pedido.empresaID),
                        sucursal_id=int(pedido.sucursalID),
                        barrio_nombre=entrega.barrioNombre,
                    )
                    entrega.barrioID = int(barrio_actualizado.idBarrio) if barrio_actualizado else None
                    pedido.costoDomicilio = _resolve_costo_domicilio(
                        db,
                        empresa_id=int(pedido.empresaID),
                        sucursal_id=int(pedido.sucursalID),
                        tipo_entrega=entrega.tipoEntrega,
                        barrio_id=(int(entrega.barrioID) if getattr(entrega, "barrioID", None) is not None else None),
                        barrio_nombre=entrega.barrioNombre,
                    )
                    needs_totals_recalc = True
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
            _sync_existing_pago_total(db, pedido=pedido)

        if (
            payload.metodosPago is not None
            or payload.canalFlora is not None
            or payload.omitirRecargoLink is not None
            or payload.descuentoMonto is not None
            or payload.descuentoNota is not None
            or payload.saldoFavorMonto is not None
            or payload.saldoFavorNota is not None
            or payload.detallePago is not None
            or payload.montoEfectivo is not None
        ):
            menu_config = _load_empresa_menu_config(db, empresa_id=int(pedido.empresaID))
            payment_field = menu_config.get("pedido_metodos_pago")
            channel_field = menu_config.get("pedido_canal_venta")
            pago_resumen_actual = _load_pago_resumen(db, pedido_id=int(pedido.idPedido), empresa_id=int(pedido.empresaID))
            metodos_fuente = payload.metodosPago if payload.metodosPago is not None else pago_resumen_actual.get("metodosPago")
            metodos_pago = [str(item or "").strip() for item in (metodos_fuente or []) if str(item or "").strip()]
            allowed_payment_methods = set(payment_field["opciones"]) if payment_field else set()
            if payment_field and not metodos_pago:
                raise HTTPException(
                    status_code=400,
                    detail={"code": "PAYMENT_METHOD_REQUIRED", "message": f"{payment_field['titulo'] or 'Método de pago'} es obligatorio"},
                )
            invalid_payment_methods = [item for item in metodos_pago if allowed_payment_methods and item not in allowed_payment_methods]
            if invalid_payment_methods:
                raise HTTPException(
                    status_code=400,
                    detail={"code": "PAYMENT_METHOD_INVALID", "message": f"Métodos de pago inválidos: {', '.join(invalid_payment_methods)}"},
                )

            canal_value = payload.canalFlora if payload.canalFlora is not None else pago_resumen_actual.get("canalFlora")
            canal_flora = str(canal_value or "").strip() or None
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

            descuento_monto = Decimal(str(
                payload.descuentoMonto
                if payload.descuentoMonto is not None
                else pago_resumen_actual.get("descuentoMonto") or 0
            ))
            saldo_favor_monto = Decimal(str(
                payload.saldoFavorMonto
                if payload.saldoFavorMonto is not None
                else pago_resumen_actual.get("saldoFavorMonto") or 0
            ))
            if descuento_monto < 0:
                raise HTTPException(
                    status_code=400,
                    detail={"code": "ORDER_DISCOUNT_INVALID", "message": "El descuento debe ser un valor entero positivo."},
                )
            if saldo_favor_monto < 0:
                raise HTTPException(
                    status_code=400,
                    detail={"code": "ORDER_SALDO_FAVOR_INVALID", "message": "El saldo a favor debe ser un valor entero positivo."},
                )

            omitir_recargo_link = bool(
                payload.omitirRecargoLink
                if payload.omitirRecargoLink is not None
                else pago_resumen_actual.get("omitirRecargoLink")
            )
            ajustes = _build_pedido_adjustments(
                subtotal=Decimal(str(pedido.totalBruto or 0)),
                iva=Decimal(str(pedido.totalIva or 0)),
                domicilio=Decimal(str(getattr(pedido, "costoDomicilio", 0) or 0)),
                metodos_pago=metodos_pago,
                omitir_recargo_link=omitir_recargo_link,
                descuento_monto=descuento_monto,
                saldo_favor_monto=saldo_favor_monto,
            )
            pedido.totalNeto = ajustes["total"]

            detalle_pago = payload.detallePago if payload.detallePago is not None else pago_resumen_actual.get("detallePago")
            monto_efectivo = (
                Decimal(str(payload.montoEfectivo))
                if payload.montoEfectivo is not None
                else (Decimal(str(pago_resumen_actual.get("montoEfectivo"))) if pago_resumen_actual.get("montoEfectivo") is not None else None)
            )

            if len(metodos_pago) > 1:
                if not isinstance(detalle_pago, list) or len(detalle_pago) < len(metodos_pago):
                    raise HTTPException(
                        status_code=400,
                        detail={"code": "PAYMENT_BREAKDOWN_REQUIRED", "message": "Debes indicar el monto correspondiente para cada método de pago."},
                    )
                breakdown_total = Decimal("0.00")
                breakdown_methods = set()
                for item in detalle_pago:
                    if not isinstance(item, dict):
                        continue
                    metodo = str(item.get("metodo") or item.get("metodoPago") or "").strip()
                    monto = Decimal(str(item.get("monto") or item.get("valor") or item.get("amount") or 0))
                    if not metodo or monto <= 0:
                        continue
                    breakdown_methods.add(metodo)
                    breakdown_total += monto
                if any(metodo not in breakdown_methods for metodo in metodos_pago):
                    raise HTTPException(
                        status_code=400,
                        detail={"code": "PAYMENT_BREAKDOWN_REQUIRED", "message": "Debes indicar el monto correspondiente para cada método de pago."},
                    )
                if _round_money_decimal(breakdown_total) != _round_money_decimal(ajustes["total"]):
                    raise HTTPException(
                        status_code=400,
                        detail={"code": "PAYMENT_BREAKDOWN_TOTAL_INVALID", "message": "La suma de los montos por método de pago debe ser igual al total del pedido."},
                    )

            monto_pago = Decimal(str(pedido.totalNeto or pedido.totalBruto or 0))
            _upsert_pago_flora(
                db,
                pedido_id=int(pedido.idPedido),
                empresa_id=int(pedido.empresaID),
                monto=monto_pago,
                metodos_pago=metodos_pago,
                canal_flora=canal_flora,
                detalle_pago=detalle_pago,
                monto_efectivo=monto_efectivo,
                omitir_recargo_link=omitir_recargo_link,
                descuento_pct=ajustes["descuentoPct"],
                descuento_nota=payload.descuentoNota if payload.descuentoNota is not None else pago_resumen_actual.get("descuentoNota"),
                recargo_link_pct=ajustes["recargoLinkPct"],
                recargo_link_monto=ajustes["recargoLinkMonto"],
                descuento_monto=ajustes["descuentoMonto"],
                saldo_favor_monto=ajustes["saldoFavorMonto"],
                saldo_favor_nota=payload.saldoFavorNota if payload.saldoFavorNota is not None else pago_resumen_actual.get("saldoFavorNota"),
            )

        _audit_pedido_action(
            db=db,
            actor=auth,
            pedido=pedido,
            accion="GUARDAR_PEDIDO",
            estado_origen_id=(int(pedido.estadoPedidoID) if pedido.estadoPedidoID is not None else None),
            estado_destino_id=(int(pedido.estadoPedidoID) if pedido.estadoPedidoID is not None else None),
            extra={
                "detalleID": (int(payload.detalleID) if payload.detalleID is not None else None),
                "productoID": (int(payload.productoID) if payload.productoID is not None else None),
                "barrioNombre": payload.barrioNombre,
                "fechaEntrega": payload.fechaEntrega,
                "horaEntrega": payload.horaEntrega,
            },
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


@router.post("/pedido/{pedido_id}/detalle", dependencies=[Depends(require_module_access("pedidos", "puedeEditar"))])
def agregar_detalle_pedido(
    pedido_id: int,
    payload: AgregarDetallePedidoRequest,
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

        producto = (
            db.query(Producto)
            .filter(
                Producto.idProducto == int(payload.productoID),
                Producto.empresaID == int(pedido.empresaID),
            )
            .first()
        )
        if not producto:
            raise HTTPException(
                status_code=404,
                detail={"code": "PRODUCTO_NOT_FOUND", "message": "Arreglo no encontrado"},
            )

        cantidad = Decimal(str(payload.cantidad or 1))
        if cantidad <= 0:
            raise HTTPException(
                status_code=400,
                detail={"code": "PEDIDO_CANTIDAD_INVALIDA", "message": "La cantidad debe ser mayor que cero"},
            )

        existing_detail = (
            db.query(PedidoDetalle)
            .filter(
                PedidoDetalle.pedidoID == int(pedido.idPedido),
                PedidoDetalle.empresaID == int(pedido.empresaID),
                PedidoDetalle.productoID == int(payload.productoID),
            )
            .order_by(PedidoDetalle.idPedidoDetalle.asc())
            .first()
        )

        if _is_custom_producto(producto):
            if payload.productoPrecio is None:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": "PEDIDO_PRECIO_SOLO_PERSONALIZADO",
                        "message": "Debes indicar un precio válido para el arreglo personalizado.",
                    },
                )
            precio_unitario = _quantize_peso_entero(payload.productoPrecio)
            if precio_unitario <= 0:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": "PEDIDO_PRECIO_INVALIDO",
                        "message": "Debes indicar un precio válido para el arreglo personalizado.",
                    },
                )
        else:
            precio_unitario = _find_branch_product_price(
                db,
                empresa_id=int(pedido.empresaID),
                sucursal_id=int(pedido.sucursalID),
                producto_id=int(payload.productoID),
            )

        observaciones = (
            _sanitize_producto_observacion(payload.productoObservaciones, producto=producto)
            if has_observaciones_personalizados
            else None
        )

        if existing_detail:
            existing_detail.cantidad = Decimal(str(existing_detail.cantidad or 0)) + cantidad
            if _is_custom_producto(producto):
                existing_detail.precioUnitario = precio_unitario
            if has_observaciones_personalizados and observaciones and not getattr(existing_detail, "observacionesPersonalizados", None):
                existing_detail.observacionesPersonalizados = observaciones
            detalle_id = int(existing_detail.idPedidoDetalle)
            action = "merged"
        else:
            detalle = PedidoDetalle(
                empresaID=int(pedido.empresaID),
                sucursalID=int(pedido.sucursalID),
                pedidoID=int(pedido.idPedido),
                productoID=int(payload.productoID),
                cantidad=cantidad,
                precioUnitario=precio_unitario,
                ivaUnitario=Decimal("0.00"),
                subtotal=Decimal("0.00"),
                observacionesPersonalizados=observaciones if has_observaciones_personalizados else None,
            )
            db.add(detalle)
            db.flush()
            detalle_id = int(detalle.idPedidoDetalle)
            action = "created"

        cliente = (
            db.query(Cliente)
            .filter(
                Cliente.idCliente == int(pedido.clienteID),
                Cliente.empresaID == int(pedido.empresaID),
            )
            .first()
        )
        _recalculate_pedido_financials(
            db,
            pedido=pedido,
            aplica_iva=_normalize_ident_type(getattr(cliente, "tipoIdent", None)) == "NIT",
        )
        _sync_existing_pago_total(db, pedido=pedido)
        db.commit()
        return {
            "status": "ok",
            "action": action,
            "pedidoID": int(pedido.idPedido),
            "detalleID": detalle_id,
        }
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        pedido_logger.error("Error SQL agregando detalle de pedido. pedido_id=%s", pedido_id, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "PEDIDO_DETALLE_CREATE_DB_ERROR",
                "message": "Error interno del servidor",
                "module": "pedido",
            },
        )
    except Exception:
        db.rollback()
        pedido_logger.error("Error inesperado agregando detalle de pedido. pedido_id=%s", pedido_id, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "PEDIDO_DETALLE_CREATE_INTERNAL_ERROR",
                "message": "Error interno del servidor",
                "module": "pedido",
            },
        )


@router.delete("/pedido/{pedido_id}/detalle/{detalle_id}", dependencies=[Depends(require_module_access("pedidos", "puedeEditar"))])
def eliminar_detalle_pedido(
    pedido_id: int,
    detalle_id: int,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    try:
        empresa_id = int(auth.empresaID)
        pedido = (
            db.query(Pedido)
            .filter(Pedido.idPedido == pedido_id, Pedido.empresaID == empresa_id)
            .first()
        )
        if not pedido:
            raise HTTPException(status_code=404, detail={"code": "PEDIDO_NOT_FOUND", "message": "Pedido no encontrado"})

        estado_nombre = _estado_pedido_nombre(db, pedido.estadoPedidoID)
        es_admin = is_empresa_admin_context(auth) or is_super_admin_context(auth)
        if estado_nombre not in {"PENDIENTE", "CREADO"} and not (estado_nombre == "APROBADO" and es_admin):
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "PEDIDO_DETALLE_DELETE_INVALID_STATE",
                    "message": "Solo administradores pueden eliminar arreglos en pedidos aprobados.",
                },
            )

        detalle = (
            db.query(PedidoDetalle)
            .filter(
                PedidoDetalle.idPedidoDetalle == detalle_id,
                PedidoDetalle.pedidoID == pedido_id,
                PedidoDetalle.empresaID == empresa_id,
            )
            .first()
        )
        if not detalle:
            raise HTTPException(
                status_code=404,
                detail={"code": "PEDIDO_DETALLE_NOT_FOUND", "message": "Arreglo no encontrado dentro del pedido."},
            )

        total_detalles = (
            db.query(func.count(PedidoDetalle.idPedidoDetalle))
            .filter(PedidoDetalle.pedidoID == pedido_id, PedidoDetalle.empresaID == empresa_id)
            .scalar()
        )
        if int(total_detalles or 0) <= 1:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "PEDIDO_DETALLE_LAST_ITEM",
                    "message": "No puedes eliminar el único arreglo del pedido.",
                },
            )

        producciones_detalle = (
            db.query(Produccion)
            .filter(
                Produccion.pedidoID == pedido_id,
                Produccion.pedidoDetalleID == detalle_id,
                Produccion.empresaID == empresa_id,
            )
            .all()
        )
        estado_cancelado_id = produccion_service.estado_produccion_id(db, produccion_service.ESTADO_CANCELADO)
        now = datetime.now(timezone.utc)
        for produccion in producciones_detalle:
            if int(produccion.estado or 0) == int(estado_cancelado_id):
                continue
            if not produccion_service.transicion_produccion_permitida(
                db,
                empresa_id=empresa_id,
                origen=produccion.estado,
                destino=produccion_service.ESTADO_CANCELADO,
            ):
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": "PRODUCCION_TRANSITION_INVALID",
                        "message": "No hay transición configurada para cancelar la producción del arreglo.",
                    },
                )
            produccion.estado = estado_cancelado_id
            produccion.updatedAt = now
            nota_cancelacion = f"Cancelado por eliminacion del arreglo {detalle_id} en pedido {pedido_id}."
            produccion.observacionesInternas = (
                f"{str(produccion.observacionesInternas).strip()}\n{nota_cancelacion}"
                if produccion.observacionesInternas
                else nota_cancelacion
            )

        db.delete(detalle)
        db.flush()
        cliente = db.query(Cliente).filter(Cliente.idCliente == pedido.clienteID).first()
        _recalculate_pedido_financials(
            db,
            pedido=pedido,
            aplica_iva=_normalize_ident_type(getattr(cliente, "tipoIdent", None)) == "NIT",
        )
        _sync_existing_pago_total(db, pedido=pedido)
        db.commit()
        return {"status": "ok", "pedidoID": int(pedido.idPedido), "detalleID": int(detalle_id)}
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        pedido_logger.error("Error SQL eliminando detalle de pedido. pedido_id=%s detalle_id=%s", pedido_id, detalle_id, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "PEDIDO_DETALLE_DELETE_DB_ERROR",
                "message": "Error interno del servidor",
                "module": "pedido",
            },
        )
    except Exception:
        db.rollback()
        pedido_logger.error("Error eliminando detalle de pedido. pedido_id=%s detalle_id=%s", pedido_id, detalle_id, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "PEDIDO_DETALLE_DELETE_ERROR",
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

    lineas_productos: list[str] = []
    observaciones_producto = []
    for detalle, producto in detalles:
        descripcion = str((producto.nombreProducto if producto else None) or "Producto").strip()
        cantidad = int(round(float(detalle.cantidad or 0)))
        lineas_productos.append(f"- {descripcion}")
        lineas_productos.append(f"  Cantidad: {cantidad}")
        observacion_detalle = str(getattr(detalle, "observacionesPersonalizados", "") or "").strip()
        if observacion_detalle:
            observaciones_producto.append(observacion_detalle)
    productos_texto = "\n".join(lineas_productos) if lineas_productos else "Sin productos"

    observacion_entrega = str((entrega.observacionGeneral if entrega else None) or "").strip()
    observacion_productos = " | ".join(observaciones_producto).strip()
    observaciones_factura = [
        f"Observaciones productos: {observacion_productos}" if observacion_productos else None,
        f"Observaciones entrega: {observacion_entrega}" if observacion_entrega else None,
    ]
    observaciones = "\n".join([item for item in observaciones_factura if item]) or "Sin observaciones"
    empresa_nombre = str(
        (getattr(empresa, "nombreComercial", None) or getattr(empresa, "nombreEmpresa", None) or "FLORA - TIENDA DE FLORES")
    ).strip()
    empresa_partes = [part.strip() for part in empresa_nombre.split(" - ", 1) if part.strip()]
    empresa_titulo = empresa_partes[0] if empresa_partes else empresa_nombre
    empresa_subtitulo = empresa_partes[1] if len(empresa_partes) > 1 else "Tienda de Flores"
    forma_pago = str(pago_resumen.get("metodoPago") or "No especificada").strip() or "No especificada"
    metodos_pago = [str(item or "").strip().lower() for item in (pago_resumen.get("metodosPago") or []) if str(item or "").strip()]
    detalle_pago = pago_resumen.get("detallePago") or []
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
    hora_entrega_label = str((entrega.rangoHora if entrega else None) or "No especificada").strip() or "No especificada"
    zona_label = f"Zona {int(barrio.zonaID)}" if barrio and getattr(barrio, "zonaID", None) is not None else "Sin zona"
    operador_nombre = str(getattr(auth, "nombre", None) or getattr(auth, "login", None) or "-").strip() or "-"
    mensaje_final = "Gracias por su compra ✿"
    numero_legible = str(pedido.numeroPedido) if int(pedido.numeroPedido or 0) > 0 else _numero_pedido_humano(pedido)
    celular_flora = str(pago_resumen.get("canalFlora") or "No especificada").strip() or "No especificada"

    recargo_link_monto = Decimal(str(pago_resumen.get("recargoLinkMonto") or 0))
    descuento_monto = Decimal(str(pago_resumen.get("descuentoMonto") or 0))
    saldo_favor_monto = Decimal(str(pago_resumen.get("saldoFavorMonto") or 0))
    descuento_nota = str(pago_resumen.get("descuentoNota") or "").strip()
    saldo_favor_nota = str(pago_resumen.get("saldoFavorNota") or "").strip()
    lineas_pago = []
    if detalle_pago:
        for item in detalle_pago:
            metodo = str(item.get("metodo") or item.get("metodoPago") or "").strip()
            monto = Decimal(str(item.get("monto") or item.get("valor") or item.get("amount") or 0))
            if metodo:
                lineas_pago.append(f"- {metodo}: {_money_cop(monto)}")
    elif forma_pago != "No especificada":
        lineas_pago.append(f"- {forma_pago}: {_money_cop(pedido.totalNeto)}")

    contenido_lineas = [
        empresa_titulo.upper(),
        empresa_subtitulo,
        "----------------------------------------",
        f"Pedido: #{numero_legible}",
        f"Registro: {_fecha_hora_humano(pedido.fechaPedido)}",
        f"Entrega: {fecha_entrega_label}",
        f"Hora entrega: {hora_entrega_label}",
        "----------------------------------------",
        "CLIENTE",
        f"Nombre: {str((cliente.nombreCompleto if cliente else None) or '-')}",
        f"CC/NIT: {str((cliente.identificacion if cliente else None) or '-')}",
        f"Telefono: {str((cliente.telefonoCompleto if cliente else None) or (cliente.telefono if cliente else None) or '-')}",
        f"Pago: {forma_pago}",
        f"Tipo pago: {tipo_pago}",
        *(lineas_pago if lineas_pago else []),
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
        *( [f"Recargo link ({int(round(float(pago_resumen.get('recargoLinkPct') or 0)))}%): {_money_cop(recargo_link_monto)}"] if recargo_link_monto > 0 else [] ),
        *( [f"Descuento: -{_money_cop(descuento_monto)}"] if descuento_monto > 0 else [] ),
        *( [f"Nota descuento: {descuento_nota}"] if descuento_nota else [] ),
        *( [f"Saldo a favor: -{_money_cop(saldo_favor_monto)}"] if saldo_favor_monto > 0 else [] ),
        *( [f"Nota saldo a favor: {saldo_favor_nota}"] if saldo_favor_nota else [] ),
        f"Total: {_money_cop(pedido.totalNeto)}",
        "----------------------------------------",
        f"Operador: {operador_nombre}",
        f"Celular Flora: {celular_flora}",
        "----------------------------------------",
        mensaje_final,
    ]

    _mark_factura_impresa(
        db,
        pedido_id=int(pedido.idPedido),
        empresa_id=int(pedido.empresaID),
        actor_login=getattr(auth, "login", None),
    )
    db.commit()

    pdf_bytes = _render_factura_pdf(contenido_lineas)
    headers = {
        "Content-Disposition": f"attachment; filename=factura_pedido_{pedido.idPedido}.pdf"
    }
    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)


@router.get("/pedidos/trazabilidad/aprobaciones", dependencies=[Depends(require_module_access("pedidos", "puedeVer"))])
def trazabilidad_aprobaciones_pedidos(
    empresa_id: int = Query(..., alias="empresaID"),
    sucursal_id: int | None = Query(None, alias="sucursalID"),
    fecha_desde: date = Query(..., alias="fechaDesde"),
    fecha_hasta: date = Query(..., alias="fechaHasta"),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, int(empresa_id))
    _ensure_pedido_auditoria_table(db)

    params = {
        "empresa_id": int(empresa_id),
        "fecha_desde": datetime.combine(fecha_desde, datetime.min.time()),
        "fecha_hasta": datetime.combine(fecha_hasta, datetime.max.time()),
    }
    sucursal_filter = ""
    if sucursal_id is not None:
        params["sucursal_id"] = int(sucursal_id)
        sucursal_filter = " AND pa.sucursal_id = :sucursal_id "

    rows = db.execute(
        text(
            f"""
            SELECT
              pa.actor_user_id,
              pa.actor_login,
              pa.pedido_id,
              pa.sucursal_id,
              pa.accion,
              pa.created_at,
              p.numero_pedido,
              p.codigo_pedido,
              p.total_neto,
              c.nombre_completo AS cliente
            FROM petalops.pedido_auditoria pa
            LEFT JOIN petalops.pedido p
              ON p.empresa_id = pa.empresa_id
             AND p.id_pedido = pa.pedido_id
            LEFT JOIN petalops.cliente c
              ON c.empresa_id = pa.empresa_id
             AND c.cliente_id = p.cliente_id
            WHERE pa.empresa_id = :empresa_id
              AND pa.accion IN ('APROBAR_PEDIDO', 'APROBAR_PEDIDO_PIPELINE', 'GUARDAR_PEDIDO')
              AND pa.created_at >= :fecha_desde
              AND pa.created_at <= :fecha_hasta
              {sucursal_filter}
            ORDER BY pa.created_at DESC
            """
        ),
        params,
    ).mappings().all()

    resumen: dict[str, dict] = {}
    detalle = []
    for row in rows:
        actor_login = str(row.get("actor_login") or "system").strip() or "system"
        bucket = resumen.setdefault(
            actor_login,
            {
                "usuarioID": (int(row["actor_user_id"]) if row.get("actor_user_id") is not None else None),
                "usuario": actor_login,
                "pedidos": set(),
                "acciones": 0,
                "valorTotal": Decimal("0"),
                "ultimoMovimiento": None,
            },
        )
        pedido_id = int(row.get("pedido_id") or 0)
        if pedido_id:
            bucket["pedidos"].add(pedido_id)
        bucket["acciones"] += 1
        bucket["valorTotal"] += Decimal(str(row.get("total_neto") or 0))
        created_at = row.get("created_at")
        if bucket["ultimoMovimiento"] is None or (created_at and created_at > bucket["ultimoMovimiento"]):
            bucket["ultimoMovimiento"] = created_at

        detalle.append(
            {
                "usuarioID": bucket["usuarioID"],
                "usuario": actor_login,
                "pedidoID": pedido_id,
                "sucursalID": (int(row["sucursal_id"]) if row.get("sucursal_id") is not None else None),
                "numeroPedido": (int(row["numero_pedido"]) if row.get("numero_pedido") is not None else None),
                "codigoPedido": (str(row.get("codigo_pedido") or "").strip() or None),
                "cliente": str(row.get("cliente") or "-"),
                "accion": str(row.get("accion") or ""),
                "fechaAccion": created_at,
                "totalPedido": float(Decimal(str(row.get("total_neto") or 0)).quantize(Decimal("0.01"))),
            }
        )

    resumen_items = sorted(
        [
            {
                "usuarioID": data["usuarioID"],
                "usuario": data["usuario"],
                "acciones": int(data["acciones"]),
                "pedidosAprobados": len(data["pedidos"]),
                "valorTotal": float(data["valorTotal"].quantize(Decimal("0.01"))),
                "ultimoMovimiento": data["ultimoMovimiento"],
            }
            for data in resumen.values()
        ],
        key=lambda item: (-int(item["acciones"]), item["usuario"]),
    )

    return {
        "resumen": resumen_items,
        "detalle": detalle,
        "total": len(detalle),
    }


@router.get("/contabilidad/resumen", dependencies=[Depends(require_module_access("contabilidad", "puedeVer"))])
def resumen_contabilidad(
    empresa_id: int = Query(..., alias="empresaID"),
    sucursal_id: int | None = Query(None, alias="sucursalID"),
    fecha_desde: date = Query(..., alias="fechaDesde"),
    fecha_hasta: date = Query(..., alias="fechaHasta"),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, int(empresa_id))
    order_query = (
        db.query(Pedido, EstadoPedido)
        .join(EstadoPedido, EstadoPedido.idEstadoPedido == Pedido.estadoPedidoID)
        .filter(
            Pedido.empresaID == int(empresa_id),
            Pedido.fechaPedido >= datetime.combine(fecha_desde, datetime.min.time()),
            Pedido.fechaPedido <= datetime.combine(fecha_hasta, datetime.max.time()),
            func.upper(EstadoPedido.nombreEstado).in_(["APROBADO", "PAGADO"]),
        )
    )
    if sucursal_id is not None:
        order_query = order_query.filter(Pedido.sucursalID == int(sucursal_id))

    order_rows = order_query.order_by(Pedido.fechaPedido.asc(), Pedido.idPedido.asc()).all()
    pedido_ids = [int(pedido.idPedido) for pedido, _ in order_rows]
    if not pedido_ids:
        return {"orderRows": [], "arrangementRows": [], "paymentAccountRows": []}

    detalle_rows = (
        db.query(PedidoDetalle, Producto)
        .outerjoin(Producto, Producto.idProducto == PedidoDetalle.productoID)
        .filter(
            PedidoDetalle.empresaID == int(empresa_id),
            PedidoDetalle.pedidoID.in_(pedido_ids),
        )
        .all()
    )
    detalles_por_pedido: dict[int, list[tuple[PedidoDetalle, Producto | None]]] = {}
    for detalle, producto in detalle_rows:
        detalles_por_pedido.setdefault(int(detalle.pedidoID), []).append((detalle, producto))

    pagos_por_pedido = _load_pago_resumen_batch(db, empresa_id=int(empresa_id), pedido_ids=pedido_ids)

    resumen_por_fecha: dict[str, dict] = {}
    arreglos_map: dict[str, dict] = {}
    cuentas_map: dict[str, dict] = {}
    total_recaudo_global = Decimal("0.00")

    for pedido, _estado in order_rows:
        pedido_id = int(pedido.idPedido)
        fecha_key = _fecha_pedido_str(pedido.fechaPedido) or "Sin fecha"
        pago_resumen = pagos_por_pedido.get(pedido_id, {})
        subtotal = Decimal(str(pedido.totalBruto or 0))
        iva = Decimal(str(pedido.totalIva or 0))
        domicilio = Decimal(str(_pedido_domicilio_valor(pedido)))
        total = Decimal(str(pedido.totalNeto or 0))
        recargos = Decimal(str(pago_resumen.get("recargoLinkMonto") or 0))
        descuentos = Decimal(str(pago_resumen.get("descuentoMonto") or 0))
        efectivo = Decimal("0.00")
        for entry in (pago_resumen.get("detallePago") or []):
            metodo = str(entry.get("metodo") or entry.get("metodoPago") or "").strip()
            monto = Decimal(str(entry.get("monto") or entry.get("valor") or 0))
            if _is_cash_payment_method(metodo):
                efectivo += monto

        current = resumen_por_fecha.get(fecha_key) or {
            "fecha": fecha_key,
            "cantidadPedidos": 0,
            "totalArreglos": Decimal("0.00"),
            "totalDomicilios": Decimal("0.00"),
            "totalRecargos": Decimal("0.00"),
            "totalDescuentos": Decimal("0.00"),
            "totalVenta": Decimal("0.00"),
            "totalEfectivo": Decimal("0.00"),
        }
        current["cantidadPedidos"] += 1
        current["totalArreglos"] += subtotal + iva
        current["totalDomicilios"] += domicilio
        current["totalRecargos"] += recargos
        current["totalDescuentos"] += descuentos
        current["totalVenta"] += total
        current["totalEfectivo"] += efectivo
        resumen_por_fecha[fecha_key] = current

        for detalle, producto in detalles_por_pedido.get(pedido_id, []):
            codigo = str(getattr(producto, "codigoProducto", "") or "").strip()
            nombre = str(getattr(producto, "nombreProducto", None) or "Arreglo").strip() or "Arreglo"
            producto_id = int(detalle.productoID or 0) if detalle.productoID is not None else 0
            key = f"{producto_id or 'na'}::{codigo or 'sin-codigo'}::{nombre}"
            row = arreglos_map.get(key) or {
                "key": key,
                "productoId": producto_id or None,
                "codigo": codigo or None,
                "nombre": nombre,
                "unidades": Decimal("0.00"),
                "pedidoIDs": set(),
                "totalVendido": Decimal("0.00"),
            }
            row["unidades"] += Decimal(str(detalle.cantidad or 0))
            row["pedidoIDs"].add(pedido_id)
            row["totalVendido"] += Decimal(str(detalle.subtotal or 0))
            arreglos_map[key] = row

        payment_entries = pago_resumen.get("detallePago") or []
        if not payment_entries:
            metodo_pago = str(pago_resumen.get("metodoPago") or "").strip()
            if metodo_pago:
                payment_entries = [{"metodo": metodo_pago, "monto": float(total)}]
        for entry in payment_entries:
            cuenta = str(entry.get("metodo") or entry.get("metodoPago") or entry.get("nombre") or "Sin especificar").strip() or "Sin especificar"
            key = cuenta.casefold()
            row = cuentas_map.get(key) or {
                "key": key,
                "cuenta": cuenta,
                "pedidosSet": set(),
                "metodosSet": set(),
                "totalRecaudado": Decimal("0.00"),
                "ultimoMovimiento": fecha_key if fecha_key != "Sin fecha" else "",
            }
            monto = Decimal(str(entry.get("monto") or entry.get("valor") or entry.get("amount") or 0))
            row["pedidosSet"].add(pedido_id)
            row["metodosSet"].add(cuenta)
            row["totalRecaudado"] += monto
            if fecha_key != "Sin fecha" and (not row["ultimoMovimiento"] or fecha_key > row["ultimoMovimiento"]):
                row["ultimoMovimiento"] = fecha_key
            cuentas_map[key] = row
            total_recaudo_global += monto

    order_rows_payload = sorted(
        [
            {
                "fecha": item["fecha"],
                "cantidadPedidos": int(item["cantidadPedidos"]),
                "totalArreglos": float(item["totalArreglos"].quantize(Decimal("0.01"))),
                "totalDomicilios": float(item["totalDomicilios"].quantize(Decimal("0.01"))),
                "totalRecargos": float(item["totalRecargos"].quantize(Decimal("0.01"))),
                "totalDescuentos": float(item["totalDescuentos"].quantize(Decimal("0.01"))),
                "totalVenta": float(item["totalVenta"].quantize(Decimal("0.01"))),
                "totalEfectivo": float(item["totalEfectivo"].quantize(Decimal("0.01"))),
            }
            for item in resumen_por_fecha.values()
        ],
        key=lambda item: item["fecha"],
    )
    arrangement_rows_payload = sorted(
        [
            {
                "key": item["key"],
                "productoId": item["productoId"],
                "codigo": item["codigo"],
                "nombre": item["nombre"],
                "unidades": float(item["unidades"].quantize(Decimal("0.01"))),
                "pedidos": len(item["pedidoIDs"]),
                "pedidoIDs": sorted(item["pedidoIDs"]),
                "totalVendido": float(item["totalVendido"].quantize(Decimal("0.01"))),
            }
            for item in arreglos_map.values()
        ],
        key=lambda item: (-float(item["unidades"]), -float(item["totalVendido"]), item["nombre"]),
    )
    payment_rows_payload = sorted(
        [
            {
                "key": item["key"],
                "cuenta": item["cuenta"],
                "pedidos": len(item["pedidosSet"]),
                "metodos": sorted(item["metodosSet"]),
                "totalRecaudado": float(item["totalRecaudado"].quantize(Decimal("0.01"))),
                "promedioPedido": float(
                    (item["totalRecaudado"] / Decimal(len(item["pedidosSet"]))).quantize(Decimal("0.01"))
                ) if item["pedidosSet"] else 0.0,
                "participacionPct": float(
                    ((item["totalRecaudado"] / total_recaudo_global) * Decimal("100")).quantize(Decimal("0.01"))
                ) if total_recaudo_global > 0 else 0.0,
                "ultimoMovimiento": item["ultimoMovimiento"] or "-",
            }
            for item in cuentas_map.values()
        ],
        key=lambda item: (-float(item["totalRecaudado"]), -int(item["pedidos"]), item["cuenta"]),
    )

    return {
        "orderRows": order_rows_payload,
        "arrangementRows": arrangement_rows_payload,
        "paymentAccountRows": payment_rows_payload,
    }


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

    estado_origen_id = int(pedido.estadoPedidoID)

    if int(pedido.numeroPedido or 0) <= 0 or not str(pedido.codigoPedido or "").strip():
        numero_pedido, codigo_pedido = generar_numeracion_pedido(
            db=db,
            empresa_id=int(pedido.empresaID),
            sucursal_id=int(pedido.sucursalID),
        )
        pedido.numeroPedido = numero_pedido
        pedido.codigoPedido = codigo_pedido
    if int(pedido.numeroPedido or 0) <= 0 or not str(pedido.codigoPedido or "").strip():
        raise HTTPException(status_code=500, detail="No fue posible asignar el número del pedido al aprobar.")

    pedido.estadoPedidoID = estado_aprobado.idEstadoPedido
    pedido.motivoRechazo = None
    pedido.updatedAt = datetime.now(timezone.utc)

    produccion = asegurar_produccion_desde_pedido_aprobado_por_detalle(
        db=db,
        pedido=pedido,
        dias_anticipacion=_dias_anticipacion_produccion(),
        usuario="pedido.aprobar",
    )
    _audit_pedido_action(
        db=db,
        actor=auth,
        pedido=pedido,
        accion="APROBAR_PEDIDO",
        estado_origen_id=estado_origen_id,
        estado_destino_id=int(estado_aprobado.idEstadoPedido),
        extra={
            "numeroPedido": int(pedido.numeroPedido or 0),
            "codigoPedido": str(pedido.codigoPedido or "").strip() or None,
        },
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

    estado_origen_id = int(pedido.estadoPedidoID)
    estado_actual = _estado_pedido_nombre(db, estado_origen_id)
    es_pendiente = estado_actual in {"CREADO", "PENDIENTE"}
    es_aprobado = estado_actual in {"APROBADO", "PAGADO"}
    if not es_pendiente and not (es_aprobado and (is_empresa_admin_context(auth) or is_super_admin_context(auth))):
        raise HTTPException(status_code=400, detail="Solo administradores pueden cancelar pedidos aprobados")

    estado_rechazado = (
        _buscar_estado_por_nombre(db, "CANCELADO")
        if es_aprobado
        else _buscar_estado_por_nombre(db, "RECHAZADO", "CANCELADO")
    )
    if not estado_rechazado:
        raise HTTPException(status_code=400, detail="No existe estado de rechazo/cancelación activo")

    if not _transicion_pedido_permitida(
        db,
        int(pedido.empresaID),
        estado_origen_id,
        int(estado_rechazado.idEstadoPedido),
    ):
        raise HTTPException(status_code=400, detail="Transición de estado inválida para el pedido")

    pedido.estadoPedidoID = estado_rechazado.idEstadoPedido
    pedido.motivoRechazo = motivo[:300]
    pedido.updatedAt = datetime.now(timezone.utc)
    _audit_pedido_action(
        db=db,
        actor=auth,
        pedido=pedido,
        accion=("CANCELAR_PEDIDO_APROBADO" if es_aprobado else "RECHAZAR_PEDIDO"),
        estado_origen_id=estado_origen_id,
        estado_destino_id=int(estado_rechazado.idEstadoPedido),
        extra={"motivo": pedido.motivoRechazo},
    )
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
        if int(pedido.numeroPedido or 0) <= 0 or not str(pedido.codigoPedido or "").strip():
            raise HTTPException(status_code=500, detail="No fue posible asignar el número del pedido al aprobar.")
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
        _audit_pedido_action(
            db=db,
            actor=auth,
            pedido=pedido,
            accion="APROBAR_PEDIDO_PIPELINE",
            estado_origen_id=int(estado_actual),
            estado_destino_id=int(nuevo_estado_id),
            extra={
                "numeroPedido": int(pedido.numeroPedido or 0),
                "codigoPedido": str(pedido.codigoPedido or "").strip() or None,
            },
        )

    db.commit()

    return {"status": "ok", "nuevoEstado": nuevo_estado_id, "produccion": produccion}
