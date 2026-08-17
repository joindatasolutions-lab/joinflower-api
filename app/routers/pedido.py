import json
import os
import re
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from fastapi.responses import Response
from sqlalchemy.orm import Session, load_only
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy import and_, or_, cast, String, func, text
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
import textwrap
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from app.core.timezone import as_colombia_naive_datetime, colombia_now_naive
from app.database import get_db
from app.models.producto import Producto
from app.models.barrio import Barrio
from app.models.cliente import Cliente
from app.models.empresa import Empresa
from app.models.pedido import Pedido
from app.models.pedidodetalle import PedidoDetalle
from app.models.produccion import Produccion
from app.models.estadopedido import EstadoPedido
from app.models.entrega import Entrega
from app.models.sucursal import Sucursal

from app.schemas.pedido import (
    PedidoCheckoutRequest,
    PedidoCheckoutResponse,
    PedidoCreate,
    PedidoManualRequest,
    PedidoManualResponse,
    PedidoListResponse,
    PedidoListItem,
    PedidoListKpiSummary,
    PedidoListProducto,
    PedidoDetalleResponse,
    PedidoDetalleProducto,
    RechazarPedidoRequest,
)
from app.services import caja_service
from app.services import domicilio_service
from app.services.empresa_menu_service import sync_empresa_menu_opciones
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
from app.middlewares.rate_limit import limiter, rate_limit

router = APIRouter()
pedido_logger = get_logger("pedido")

FLORA_EMPRESA_ID = 3

STORE_PICKUP_DELIVERY_VALUES = (
    "recogida_en_tienda",
    "recoger_en_tienda",
    "retiro_en_tienda",
    "tienda",
    "recogida",
    "recoger",
)
LINK_PAYMENT_METHODS = {"link bold", "link payu", "link wompi"}
LINK_SURCHARGE_PCT = Decimal("5.00")


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
    value = as_colombia_naive_datetime(value)
    if not value:
        return None
    return value.date().isoformat()


def _hora_pedido_str(value: datetime | None) -> str | None:
    value = as_colombia_naive_datetime(value)
    if not value:
        return None
    return value.strftime("%H:%M:%S")


def _fecha_hora_humano(value: datetime | None) -> str:
    value = as_colombia_naive_datetime(value)
    if not value:
        return "No especificada"
    return value.strftime("%d/%m/%Y %H:%M")


def _fecha_filtro_pedido(value: datetime | None) -> datetime | None:
    return as_colombia_naive_datetime(value)


def _fecha_respuesta_pedido(value: datetime | None) -> datetime | None:
    return as_colombia_naive_datetime(value)


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


def _factura_empresa_labels(empresa, sucursal, empresa_id: int) -> tuple[str, str]:
    nombre_empresa = str(
        (getattr(empresa, "nombreComercial", None) or getattr(empresa, "nombreEmpresa", None) or "")
    ).strip()
    if not nombre_empresa:
        nombre_empresa = str(getattr(sucursal, "nombreSucursal", None) or "PetalOps").strip() or "PetalOps"

    partes = [part.strip() for part in nombre_empresa.split(" - ", 1) if part.strip()]
    titulo = partes[0] if partes else nombre_empresa
    subtitulo = partes[1] if len(partes) > 1 else ""
    if not subtitulo and int(empresa_id) == FLORA_EMPRESA_ID:
        subtitulo = "Tienda de Flores"
    return titulo, subtitulo


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


def _ensure_transiciones_pedido_defaults(db: Session, empresa_id: int) -> None:
    db.execute(
        text(
            """
            WITH estados AS (
                SELECT id_estado_pedido, UPPER(TRIM(nombre_estado)) AS nombre_estado
                FROM petalops.estado_pedido
            ), pares(origen, destino) AS (
                VALUES
                    ('CREADO', 'APROBADO'),
                    ('CREADO', 'CANCELADO'),
                    ('PENDIENTE', 'APROBADO'),
                    ('PENDIENTE', 'CANCELADO'),
                    ('APROBADO', 'CANCELADO')
            )
            INSERT INTO petalops.transicion_estado_pedido (
                empresa_id,
                estado_origen_id,
                estado_destino_id,
                created_at
            )
            SELECT
                :empresa_id,
                eo.id_estado_pedido,
                ed.id_estado_pedido,
                CURRENT_TIMESTAMP
            FROM pares p
            JOIN estados eo ON eo.nombre_estado = p.origen
            JOIN estados ed ON ed.nombre_estado = p.destino
            WHERE NOT EXISTS (
                SELECT 1
                FROM petalops.transicion_estado_pedido tep
                WHERE tep.empresa_id = :empresa_id
            )
            ON CONFLICT (empresa_id, estado_origen_id, estado_destino_id) DO NOTHING
            """
        ),
        {"empresa_id": int(empresa_id)},
    )


def _transicion_pedido_permitida(db: Session, empresa_id: int, origen_id: int | None, destino_id: int | None) -> bool:
    if origen_id is None or destino_id is None:
        return False

    origen_id = int(origen_id)
    destino_id = int(destino_id)
    if origen_id == destino_id:
        return True

    _ensure_transiciones_pedido_defaults(db, int(empresa_id))
    transition = db.execute(
        text(
            """
            SELECT 1
            FROM petalops.transicion_estado_pedido
            WHERE empresa_id = :empresa_id
              AND estado_origen_id = :origen_id
              AND estado_destino_id = :destino_id
            LIMIT 1
            """
        ),
        {
            "empresa_id": int(empresa_id),
            "origen_id": origen_id,
            "destino_id": destino_id,
        },
    ).first()
    return transition is not None


def _estado_pedido_editable(db: Session, estado_pedido_id: int | None) -> bool:
    return _estado_pedido_nombre(db, estado_pedido_id) not in {"ENTREGADO", "CANCELADO", "RECHAZADO"}


def _append_operational_cancel_note(current: str | None, note: str) -> str:
    current_text = str(current or "").strip()
    if not current_text:
        return note
    if note in current_text:
        return current_text
    return f"{current_text}\n{note}"


def _sincronizar_cancelacion_operativa_desde_pedido(
    db: Session,
    pedido: Pedido,
    *,
    motivo: str | None = None,
) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    note = f"Cancelado desde pedidos por estado del pedido {int(pedido.idPedido)}."
    motivo_text = str(motivo or "").strip()
    if motivo_text:
        note = f"{note} Motivo: {motivo_text[:300]}"

    producciones_actualizadas = produccion_service.cancelar_producciones_por_pedido_cancelado(
        db,
        pedido_id=int(pedido.idPedido),
        empresa_id=int(pedido.empresaID),
        usuario="pedido.cancelacion_operativa",
        motivo=note,
    )
    entregas_actualizadas = 0

    estado_entrega_cancelado = domicilio_service.resolve_estado_entrega_id(
        db,
        domicilio_service.ESTADO_CANCELADO,
    )
    entregas = (
        db.query(Entrega)
        .filter(
            Entrega.pedidoID == int(pedido.idPedido),
            Entrega.empresaID == int(pedido.empresaID),
        )
        .all()
    )
    for entrega in entregas:
        if int(entrega.estadoEntregaID or 0) == int(estado_entrega_cancelado):
            continue
        entrega.estadoEntregaID = int(estado_entrega_cancelado)
        entrega.observaciones = _append_operational_cancel_note(
            entrega.observaciones,
            note,
        )
        entrega.updatedAt = now
        entregas_actualizadas += 1

    return {
        "produccionesCanceladas": producciones_actualizadas,
        "entregasCanceladas": entregas_actualizadas,
    }


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
    return _fecha_respuesta_pedido(
        entrega.reprogramadaPara or entrega.fechaEntregaProgramada or entrega.fechaEntrega
    )


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


def _normalizar_telefono_completo_pedido(indicativo: str | None, telefono: str | None) -> str | None:
    prefijo = str(indicativo or "").strip().replace(" ", "")
    numero = str(telefono or "").strip().replace(" ", "")
    if not prefijo and not numero:
        return None
    if prefijo and not prefijo.startswith("+"):
        prefijo = f"+{prefijo}"
    return f"{prefijo}{numero}"


def _upsert_cliente_pedido_manual(
    db: Session,
    *,
    empresa_id: int,
    tipo_ident: str | None,
    identificacion: str | None,
    indicativo: str | None,
    nombre_completo: str,
    telefono: str,
    email: str | None,
) -> Cliente:
    telefono_text = str(telefono or "").strip()
    identificacion_text = str(identificacion or "").strip()
    filters = []
    if telefono_text:
        filters.extend([Cliente.telefono == telefono_text, Cliente.telefonoCompleto == telefono_text])
    if identificacion_text:
        filters.append(Cliente.identificacion == identificacion_text)

    cliente = None
    if filters:
        cliente = (
            db.query(Cliente)
            .filter(Cliente.empresaID == int(empresa_id), or_(*filters))
            .order_by(Cliente.updatedAt.desc().nullslast(), Cliente.idCliente.desc())
            .first()
        )
    if not cliente:
        cliente = Cliente(
            empresaID=int(empresa_id),
            tipoIdent=tipo_ident or "CC",
            identificacion=_cliente_identificacion_fallback(identificacion_text, telefono_text),
            indicativo=indicativo,
            telefonoCompleto=_normalizar_telefono_completo_pedido(indicativo, telefono_text) or telefono_text or None,
            nombreCompleto=nombre_completo,
            telefono=telefono_text or None,
            email=email,
            activo=1,
            createdAt=colombia_now_naive(),
        )
        db.add(cliente)
        db.flush()
        return cliente

    cliente.tipoIdent = tipo_ident or cliente.tipoIdent or "CC"
    cliente.identificacion = identificacion_text or cliente.identificacion or _cliente_identificacion_fallback(None, telefono_text or cliente.telefono)
    cliente.indicativo = indicativo or cliente.indicativo
    cliente.nombreCompleto = nombre_completo or cliente.nombreCompleto
    cliente.telefono = telefono_text or cliente.telefono
    cliente.telefonoCompleto = (
        _normalizar_telefono_completo_pedido(indicativo or cliente.indicativo, telefono_text or cliente.telefono)
        or cliente.telefonoCompleto
    )
    cliente.email = email if email is not None else cliente.email
    cliente.updatedAt = colombia_now_naive()
    db.flush()
    return cliente


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
        domicilio=(
            Decimal("0.00")
            if _pedido_omite_costo_domicilio(pedido)
            else Decimal(str(getattr(pedido, "costoDomicilio", 0) or 0))
        ),
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


def _column_exists(db: Session, table_name: str, column_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'petalops'
              AND table_name = :table_name
              AND column_name = :column_name
            LIMIT 1
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    ).first()
    return bool(row)


def _flora_phase2_ready(db: Session) -> bool:
    required_columns = {
        "metodo_pago_catalogo": (
            "id_metodo_pago",
            "empresa_id",
            "codigo",
            "nombre",
            "orden",
            "activo",
            "created_at",
            "updated_at",
        ),
        "pago_metodo": (
            "id_pago_metodo",
            "empresa_id",
            "pago_id",
            "pedido_id",
            "metodo_pago_id",
            "monto",
            "orden",
            "created_at",
            "updated_at",
        ),
        "canal_venta": (
            "id_canal_venta",
            "empresa_id",
            "codigo",
            "nombre",
            "orden",
            "activo",
            "created_at",
            "updated_at",
        ),
        "pedido_canal_venta": (
            "empresa_id",
            "pedido_id",
            "canal_venta_id",
            "created_at",
            "updated_at",
        ),
    }
    for table_name, columns in required_columns.items():
        if not _table_exists(db, table_name):
            return False
        if not all(_column_exists(db, table_name, column_name) for column_name in columns):
            return False
    return True


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


def _mostrar_codigo_catalogo(db: Session, empresa_id: int) -> bool:
    """Config real por empresa (ver sql/alter_empresa_mostrar_codigo_catalogo.sql).
    Si la migracion aun no corrio en esta BD, mantiene el comportamiento legado (solo Flora)."""
    if not _column_exists(db, "empresa", "mostrar_codigo_catalogo"):
        return int(empresa_id) == 3
    row = db.execute(
        text("SELECT mostrar_codigo_catalogo FROM petalops.empresa WHERE id_empresa = :empresa_id"),
        {"empresa_id": int(empresa_id)},
    ).first()
    return bool(row[0]) if row and row[0] is not None else False


def _codigo_producto_visible(producto: Producto | None, mostrar_codigo_catalogo: bool) -> str | None:
    if not producto:
        return None
    codigo_producto = _codigo_producto_base(producto)
    codigo_catalogo = _codigo_catalogo_base(producto)
    if mostrar_codigo_catalogo and codigo_catalogo:
        return codigo_catalogo
    return codigo_producto


def _codigo_producto_base(producto: Producto | None) -> str | None:
    if not producto:
        return None
    return str(getattr(producto, "codigoProducto", "") or "").strip() or None


def _codigo_catalogo_base(producto: Producto | None) -> str | None:
    if not producto:
        return None
    return str(getattr(producto, "codigoCatalogo", "") or "").strip() or None


def _producto_listado_texto(producto: Producto | None, mostrar_codigo_catalogo: bool) -> str:
    nombre = str(getattr(producto, "nombreProducto", None) or "Producto").strip() or "Producto"
    codigo = _codigo_producto_visible(producto, mostrar_codigo_catalogo)
    return f"{codigo} - {nombre}" if codigo else nombre


def _producto_listado_detalle(detalle: PedidoDetalle, producto: Producto | None, mostrar_codigo_catalogo: bool) -> PedidoListProducto:
    nombre = str(getattr(producto, "nombreProducto", None) or "Producto").strip() or "Producto"
    producto_id = int(detalle.productoID or 0) if detalle.productoID is not None else 0
    return PedidoListProducto(
        productoID=producto_id,
        codigoProducto=_codigo_producto_visible(producto, mostrar_codigo_catalogo),
        codigoCatalogo=_codigo_catalogo_base(producto),
        nombreProducto=nombre,
        cantidad=float(detalle.cantidad or 0),
    )


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


def _normalize_store_pickup_value(value: str | None) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


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


def _pedido_omite_costo_domicilio(pedido: Pedido) -> bool:
    return bool(
        getattr(pedido, "omitirCostoDomicilio", False)
        or getattr(pedido, "domicilioObsequiado", False)
    )


def _manual_money(value: float | int | Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _manual_domicilio_amounts(
    *,
    domicilio: float | int | Decimal | None,
    domicilio_original: float | int | Decimal | None,
    descuento_domicilio: float | int | Decimal | None,
    domicilio_obsequiado: bool,
    omitir_costo_domicilio: bool,
    resolved_domicilio: Decimal,
) -> dict[str, Decimal | bool | None]:
    resolved = _round_money_decimal(resolved_domicilio)
    domicilio_solicitado = _manual_money(domicilio)
    original = _manual_money(domicilio_original)
    descuento = _manual_money(descuento_domicilio)
    omitido = bool(omitir_costo_domicilio or domicilio_obsequiado)

    if original is None:
        original = resolved
        if domicilio_solicitado is not None and domicilio_solicitado > 0:
            original = domicilio_solicitado

    cobrado = Decimal("0.00") if omitido else (domicilio_solicitado if domicilio_solicitado is not None else resolved)
    cobrado = _round_money_decimal(cobrado)

    if descuento is None:
        descuento = _round_money_decimal(max(original - cobrado, Decimal("0.00")))
    elif descuento < 0:
        descuento = Decimal("0.00")

    return {
        "cobrado": cobrado,
        "original": original,
        "descuento": descuento,
        "domicilioObsequiado": bool(domicilio_obsequiado),
        "omitirCostoDomicilio": bool(omitir_costo_domicilio),
    }


def _apply_pedido_domicilio_amounts(
    pedido: Pedido,
    *,
    resolved_domicilio: Decimal,
    domicilio_cobrado: float | int | Decimal | None = None,
    domicilio_original: float | int | Decimal | None = None,
    descuento_domicilio: float | int | Decimal | None = None,
    domicilio_obsequiado: bool | None = None,
    omitir_costo_domicilio: bool | None = None,
    prefer_resolved: bool = False,
) -> None:
    resolved = _round_money_decimal(resolved_domicilio)
    cobrado = _manual_money(domicilio_cobrado)
    original_payload = _manual_money(domicilio_original)
    descuento_payload = _manual_money(descuento_domicilio)

    if domicilio_obsequiado is not None:
        pedido.domicilioObsequiado = bool(domicilio_obsequiado)
    if omitir_costo_domicilio is not None:
        pedido.omitirCostoDomicilio = bool(omitir_costo_domicilio)

    if _pedido_omite_costo_domicilio(pedido):
        original = (
            (resolved if prefer_resolved else None)
            or original_payload
            or cobrado
            or _manual_money(getattr(pedido, "domicilioOriginal", None))
            or _manual_money(getattr(pedido, "costoDomicilio", None))
            or resolved
        )
        pedido.costoDomicilio = Decimal("0.00")
        pedido.domicilioOriginal = _round_money_decimal(original)
        pedido.descuentoDomicilio = _round_money_decimal(
            original if prefer_resolved else (descuento_payload or original)
        )
        return

    charged = (
        (resolved if prefer_resolved else None)
        or cobrado
        or original_payload
        or _manual_money(getattr(pedido, "costoDomicilio", None))
        or resolved
    )
    original = (
        (resolved if prefer_resolved else None)
        or original_payload
        or _manual_money(getattr(pedido, "domicilioOriginal", None))
        or charged
    )
    pedido.costoDomicilio = _round_money_decimal(charged)
    pedido.domicilioOriginal = _round_money_decimal(original)
    pedido.descuentoDomicilio = _round_money_decimal(
        descuento_payload
        if descuento_payload is not None
        else max(Decimal(str(original)) - Decimal(str(charged)), Decimal("0.00"))
    )


def _resolve_entrega_domicilio_amount(db: Session, *, pedido: Pedido, entrega: Entrega | None) -> Decimal:
    if not entrega:
        return _round_money_decimal(getattr(pedido, "costoDomicilio", None) or 0)
    return _resolve_costo_domicilio(
        db,
        empresa_id=int(pedido.empresaID),
        sucursal_id=int(pedido.sucursalID),
        tipo_entrega=getattr(entrega, "tipoEntrega", None),
        barrio_id=(int(entrega.barrioID) if getattr(entrega, "barrioID", None) is not None else None),
        barrio_nombre=getattr(entrega, "barrioNombre", None),
    )


def _payload_field_value(payload: BaseModel, name: str, missing):
    fields_set = getattr(payload, "model_fields_set", None)
    if fields_set is None:
        fields_set = getattr(payload, "__fields_set__", set())
    if name in fields_set:
        return getattr(payload, name)
    financiero_payload = getattr(payload, "financiero", None)
    if isinstance(financiero_payload, dict) and name in financiero_payload:
        return financiero_payload.get(name)
    return missing


def _payload_producto_precio_value(payload: BaseModel, missing):
    value = _payload_field_value(payload, "productoPrecio", missing)
    if value is not missing:
        return value
    return _payload_field_value(payload, "precioUnitario", missing)


def _payload_cliente_tipo_ident_value(payload: BaseModel, missing):
    value = _payload_field_value(payload, "clienteTipoIdent", missing)
    if value is not missing:
        return value
    value = _payload_field_value(payload, "tipoIdent", missing)
    if value is not missing:
        return value
    cliente_payload = getattr(payload, "cliente", None)
    if isinstance(cliente_payload, dict) and "tipoIdent" in cliente_payload:
        return cliente_payload.get("tipoIdent")
    return missing


def _sync_produccion_observaciones_internas_desde_detalle(
    db: Session,
    *,
    pedido_id: int,
    empresa_id: int,
    detalle_id: int | None,
    notas_produccion: str | None,
) -> None:
    if detalle_id is None:
        return
    estado_cancelado_id = produccion_service.estado_produccion_id(db, produccion_service.ESTADO_CANCELADO)
    producciones = (
        db.query(Produccion)
        .filter(
            Produccion.pedidoID == int(pedido_id),
            Produccion.empresaID == int(empresa_id),
            Produccion.pedidoDetalleID == int(detalle_id),
            Produccion.estado != int(estado_cancelado_id),
        )
        .all()
    )
    now = colombia_now_naive()
    for produccion in producciones:
        produccion.observacionesInternas = str(notas_produccion or "").strip() or None
        produccion.updatedAt = now


def _invalidate_factura_impresa(db: Session, *, pedido_id: int, empresa_id: int) -> None:
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
        factura_impresa=False,
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
    total = _round_money_decimal(total_despues_descuento + saldo_favor_monto)

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
            SELECT metodo_pago, proveedor, referencia, raw_respuesta, monto
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
        # Empresas sin flujo de pago Flora (sin metodo_pago/canal capturados
        # al guardar el pedido) nunca tienen fila en petalops.pago, asi que
        # antes esto no hacia nada y el aviso de "factura pendiente" quedaba
        # pegado para siempre. Se crea una fila minima solo para poder
        # persistir la marca de "impresa" — no representa un pago real.
        # metodo_pago='' (no NULL, la columna es NOT NULL) a proposito: una
        # cadena vacia la ignoran _parse_payment_methods/_load_pago_resumen*,
        # asi que esta fila placeholder no aparece como si fuera un metodo de
        # pago real capturado.
        id_pago = db.execute(
            text(
                """
                INSERT INTO petalops.pago (
                    empresa_id, pedido_id, proveedor, moneda, monto,
                    metodo_pago, raw_respuesta, fecha_pago, created_at, updated_at
                ) VALUES (
                    :empresa_id, :pedido_id, 'manual', 'COP', 0,
                    '', NULL, NOW(), NOW(), NOW()
                )
                RETURNING id_pago
                """
            ),
            {"empresa_id": int(empresa_id), "pedido_id": int(pedido_id)},
        ).scalar()
        row = {"id_pago": id_pago, "raw_respuesta": None}

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
            SELECT pedido_id, metodo_pago, proveedor, referencia, raw_respuesta, monto
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


def _approval_gate_summary(
    db: Session,
    *,
    pedido_id: int,
    empresa_id: int,
    rules: dict | None = None,
    pago_resumen: dict | None = None,
) -> dict:
    # rules/pago_resumen pueden precalcularse (una sola vez / en lote) cuando se
    # evalua esto para muchos pedidos a la vez (ej. listar_pedidos), para evitar
    # repetir las mismas consultas por cada fila.
    if rules is None:
        rules = _tenant_order_rules(db, int(empresa_id))
    if pago_resumen is None:
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

    # petalops.pago.metodo_pago es NOT NULL: cuando no hay metodos capturados
    # (empresas sin metodo_pago_catalogo configurado, ver /configuracion) se
    # usa '' en vez de None — _parse_payment_methods('') resuelve a lista
    # vacia igual que None, asi que no cambia como se lee este dato despues.
    metodo_pago = " | ".join(metodos_pago) if metodos_pago else ""
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

    if missing_methods:
        # Sin esto, el metodo nuevo queda en metodo_pago_catalogo pero nunca
        # aparece en el formulario de pedido — empresa_menu.opciones_json
        # (la fuente real de las opciones que muestra el front) no se toca
        # aqui arriba, solo el catalogo.
        sync_empresa_menu_opciones(db, empresa_id=int(empresa_id), campo="pedido_metodos_pago")

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
        caja_service.refresh_caja_por_pedido(db, pedido=pedido)
        return

    pago_resumen = _load_pago_resumen(db, pedido_id=int(pedido.idPedido), empresa_id=int(pedido.empresaID))
    metodos_pago = list(pago_resumen.get("metodosPago") or [])
    if len(metodos_pago) != 1:
        caja_service.refresh_caja_por_pedido(db, pedido=pedido)
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
        caja_service.refresh_caja_por_pedido(db, pedido=pedido)
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
    caja_service.refresh_caja_por_pedido(db, pedido=pedido)


def _build_pedido_list_kpis(
    db: Session,
    *,
    empresa_id: int,
    pedido_ids: list[int],
    estado_map: dict[int, str],
    facturas_pendientes_impresion: int,
) -> PedidoListKpiSummary:
    if not pedido_ids:
        return PedidoListKpiSummary(sinImprimir=int(facturas_pendientes_impresion))

    rows = (
        db.query(Pedido.idPedido, Pedido.totalBruto, Pedido.totalIva)
        .filter(Pedido.empresaID == int(empresa_id), Pedido.idPedido.in_(pedido_ids))
        .all()
    )

    venta_hoy = Decimal("0.00")
    pedidos_hoy = 0
    aprobados = 0
    pendientes = 0
    cancelados = 0
    cancelado_estados = {"CANCELADO", "RECHAZADO"}
    aprobado_estados = {"APROBADO", "PAGADO"}
    pendiente_estados = {"CREADO", "PENDIENTE"}

    for pedido_id, total_bruto, total_iva in rows:
        estado_nombre = str(estado_map.get(int(pedido_id), "SIN_ESTADO") or "SIN_ESTADO").strip().upper()
        if estado_nombre in cancelado_estados:
            cancelados += 1
            continue

        if estado_nombre in aprobado_estados:
            aprobados += 1
            pedidos_hoy += 1
            venta_hoy += Decimal(str(total_bruto or 0)) + Decimal(str(total_iva or 0))
        elif estado_nombre in pendiente_estados:
            pendientes += 1
            pedidos_hoy += 1

    return PedidoListKpiSummary(
        ventaHoy=float(venta_hoy.quantize(Decimal("0.01"))),
        pedidosHoy=int(pedidos_hoy),
        aprobados=int(aprobados),
        pendientes=int(pendientes),
        cancelados=int(cancelados),
        sinImprimir=int(facturas_pendientes_impresion),
    )


@router.get("/pedidos", response_model=PedidoListResponse, dependencies=[Depends(require_module_access("pedidos", "puedeVer"))])
@limiter.limit(rate_limit("pedidos_list", "100/minute"))
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

    fecha_desde_filter = _fecha_filtro_pedido(fecha_desde)
    fecha_hasta_filter = _fecha_filtro_pedido(fecha_hasta)

    if fecha_desde_filter and not has_search:
        base = base.filter(Pedido.fechaPedido >= fecha_desde_filter)

    if fecha_hasta_filter and not has_search:
        base = base.filter(Pedido.fechaPedido <= fecha_hasta_filter)

    if solo_tienda:
        tipo_entrega_norm = func.lower(
            func.replace(
                func.replace(func.coalesce(Entrega.tipoEntrega, ""), "-", "_"),
                " ",
                "_",
            )
        )
        barrio_nombre_norm = func.lower(
            func.replace(
                func.replace(func.coalesce(Entrega.barrioNombre, ""), "-", "_"),
                " ",
                "_",
            )
        )
        base = base.filter(
            or_(
                tipo_entrega_norm.in_(STORE_PICKUP_DELIVERY_VALUES),
                barrio_nombre_norm.in_(STORE_PICKUP_DELIVERY_VALUES),
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
                    func.coalesce(Producto.codigoProducto, "").ilike(term),
                    func.coalesce(Producto.codigoCatalogo, "").ilike(term),
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
        return PedidoListResponse(
            items=[],
            total=0,
            page=page,
            pageSize=page_size,
            facturasPendientesImpresion=0,
            kpis=PedidoListKpiSummary(),
        )

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
    kpis = _build_pedido_list_kpis(
        db,
        empresa_id=int(empresa_id),
        pedido_ids=candidate_ids,
        estado_map=estado_map,
        facturas_pendientes_impresion=facturas_pendientes_impresion,
    )
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
            kpis=kpis,
        )

    pago_resumen_page = {int(pedido_id): pago_resumen_map.get(int(pedido_id), {}) for pedido_id in pedido_ids}
    tenant_rules = _tenant_order_rules(db, int(empresa_id))

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
        db.query(PedidoDetalle, Producto)
        .options(
            load_only(
                Producto.idProducto,
                Producto.empresaID,
                Producto.codigoProducto,
                Producto.codigoCatalogo,
                Producto.nombreProducto,
                Producto.descripcion,
            )
        )
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

    mostrar_codigo_catalogo = _mostrar_codigo_catalogo(db, empresa_id)
    productos_por_pedido: dict[int, list[str]] = {}
    productos_detalle_por_pedido: dict[int, list[PedidoListProducto]] = {}
    for detalle, producto in detalles_rows:
        pedido_id = int(detalle.pedidoID)
        productos_por_pedido.setdefault(pedido_id, []).append(
            _producto_listado_texto(producto, mostrar_codigo_catalogo)
        )
        productos_detalle_por_pedido.setdefault(pedido_id, []).append(
            _producto_listado_detalle(detalle, producto, mostrar_codigo_catalogo)
        )

    rows_map = {int(pedido.idPedido): (pedido, cliente, entrega, estado_db) for pedido, cliente, entrega, estado_db in pedido_rows}

    items: list[PedidoListItem] = []
    for pedido_id in pedido_ids:
        pedido, cliente, entrega, estado_db = rows_map[pedido_id]
        estado_nombre = str((estado_db.nombreEstado if estado_db else "SIN_ESTADO") or "SIN_ESTADO")
        approval_gate = _approval_gate_summary(
            db,
            pedido_id=pedido_id,
            empresa_id=int(pedido.empresaID),
            rules=tenant_rules,
            pago_resumen=pago_resumen_page.get(pedido_id) or {},
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
                fecha=_fecha_respuesta_pedido(pedido.fechaPedido),
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
                productosDetalle=productos_detalle_por_pedido.get(pedido_id, []),
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
        kpis=kpis,
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
        mostrar_codigo_catalogo = _mostrar_codigo_catalogo(db, int(pedido.empresaID))

        detalles = (
            db.query(PedidoDetalle, Producto)
            .options(
                load_only(
                    Producto.idProducto,
                    Producto.empresaID,
                    Producto.codigoProducto,
                    Producto.codigoCatalogo,
                    Producto.nombreProducto,
                    Producto.descripcion,
                )
            )
            .outerjoin(Producto, Producto.idProducto == PedidoDetalle.productoID)
            .filter(PedidoDetalle.pedidoID == pedido.idPedido)
            .all()
        )

        productos = [
            PedidoDetalleProducto(
                detalleID=int(detalle.idPedidoDetalle),
                productoID=int((producto.idProducto if producto else detalle.productoID) or 0),
                codigoProducto=_codigo_producto_visible(producto, mostrar_codigo_catalogo),
                codigoCatalogo=_codigo_catalogo_base(producto),
                nombreProducto=str((producto.nombreProducto if producto else None) or "Producto"),
                cantidad=float(detalle.cantidad or 0),
                observaciones=None,
                notasProduccion=_sanitize_producto_observacion(
                    (
                        str(getattr(detalle, "observacionesPersonalizados", "")).strip()
                        if has_observaciones_personalizados and getattr(detalle, "observacionesPersonalizados", None)
                        else None
                    ),
                    producto=producto,
                ),
                observacionesPersonalizadas=(str(entrega.observaciones).strip() if entrega and entrega.observaciones else None),
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
            fecha=_fecha_respuesta_pedido(pedido.fechaPedido),
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
                "observaciones": entrega.observaciones if entrega else None,
                "observacionesPersonalizadas": entrega.observaciones if entrega else None,
            },
            financiero={
                "subtotal": float(pedido.totalBruto or 0),
                "iva": float(pedido.totalIva or 0),
                "domicilio": float(_pedido_domicilio_valor(pedido)),
                "domicilioObsequiado": bool(getattr(pedido, "domicilioObsequiado", False)),
                "omitirCostoDomicilio": bool(getattr(pedido, "omitirCostoDomicilio", False)),
                "domicilioOriginal": (
                    float(pedido.domicilioOriginal)
                    if getattr(pedido, "domicilioOriginal", None) is not None
                    else None
                ),
                "descuentoDomicilio": (
                    float(pedido.descuentoDomicilio)
                    if getattr(pedido, "descuentoDomicilio", None) is not None
                    else None
                ),
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
    precioUnitario: float | None = None
    cantidad: float | None = None
    productoObservaciones: str | None = None
    notasProduccion: str | None = None
    observacionesPersonalizadas: str | None = None
    observaciones: str | None = None
    fechaEntrega: str | None = None   # ISO date "YYYY-MM-DD"
    horaEntrega: str | None = None    # Ej. "10:00 - 12:00"
    clienteNombre: str | None = None
    clienteTelefono: str | None = None
    clienteEmail: str | None = None
    clienteTipoIdent: str | None = None
    tipoIdent: str | None = None
    clienteIdentificacion: str | None = None
    cliente: dict | None = None
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
    domicilio: float | None = None
    costoDomicilio: float | None = None
    costo_domicilio: float | None = None
    domicilioOriginal: float | None = None
    descuentoDomicilio: float | None = None
    domicilioObsequiado: bool | None = None
    domicilio_obsequiado: bool | None = None
    omitirCostoDomicilio: bool | None = None
    omitir_costo_domicilio: bool | None = None
    subtotal: float | None = None
    iva: float | None = None
    total: float | None = None
    forzarRecalculoFinanciero: bool | None = None
    financiero: dict | None = None


class AgregarDetallePedidoRequest(BaseModel):
    productoID: int
    cantidad: float | None = 1
    productoObservaciones: str | None = None
    productoPrecio: float | None = None
    precioUnitario: float | None = None


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
        missing_payload = object()
        notas_produccion_payload = _payload_field_value(payload, "notasProduccion", missing_payload)
        if notas_produccion_payload is missing_payload:
            notas_produccion_payload = _payload_field_value(payload, "productoObservaciones", missing_payload)
        observaciones_personalizadas_payload = _payload_field_value(payload, "observacionesPersonalizadas", missing_payload)
        if observaciones_personalizadas_payload is missing_payload:
            observaciones_personalizadas_payload = _payload_field_value(payload, "observaciones", missing_payload)
        producto_precio_payload = _payload_producto_precio_value(payload, missing_payload)
        cliente_tipo_ident_payload = _payload_cliente_tipo_ident_value(payload, missing_payload)
        entrega_actual: Entrega | None = None

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
                    None if notas_produccion_payload is missing_payload else notas_produccion_payload,
                    producto=producto,
                )
                _sync_produccion_observaciones_internas_desde_detalle(
                    db,
                    pedido_id=int(pedido.idPedido),
                    empresa_id=int(pedido.empresaID),
                    detalle_id=int(detalle.idPedidoDetalle),
                    notas_produccion=detalle.observacionesPersonalizados,
                )
            needs_totals_recalc = True
        elif notas_produccion_payload is not missing_payload and detalle and has_observaciones_personalizados:
            producto_actual = (
                db.query(Producto)
                .filter(
                    Producto.idProducto == int(detalle.productoID),
                    Producto.empresaID == int(pedido.empresaID),
                )
                .first()
            )
            detalle.observacionesPersonalizados = _sanitize_producto_observacion(
                notas_produccion_payload,
                producto=producto_actual,
            )
            _sync_produccion_observaciones_internas_desde_detalle(
                db,
                pedido_id=int(pedido.idPedido),
                empresa_id=int(pedido.empresaID),
                detalle_id=int(detalle.idPedidoDetalle),
                notas_produccion=detalle.observacionesPersonalizados,
            )

        if producto_precio_payload not in (missing_payload, None) and detalle:
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

            nuevo_precio = _quantize_peso_entero(producto_precio_payload)
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
        if cliente_tipo_ident_payload not in (missing_payload, None):
            cliente.tipoIdent = _normalize_ident_type(cliente_tipo_ident_payload)
            needs_totals_recalc = True
        if payload.clienteIdentificacion is not None:
            cliente.identificacion = str(payload.clienteIdentificacion).strip() or None

        if (
            any(
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
            )
            or observaciones_personalizadas_payload is not missing_payload
        ):
            entrega_actual = (
                db.query(Entrega)
                .filter(
                    Entrega.pedidoID == pedido_id,
                    Entrega.empresaID == int(pedido.empresaID),
                )
                .order_by(Entrega.intentoNumero.desc(), Entrega.idEntrega.desc())
                .first()
            )
            if entrega_actual:
                if payload.fechaEntrega is not None:
                    entrega_actual.fechaEntregaProgramada = _parse_iso_date(payload.fechaEntrega)
                if payload.horaEntrega is not None:
                    entrega_actual.rangoHora = payload.horaEntrega or None
                if payload.destinatarioNombre is not None:
                    entrega_actual.destinatario = str(payload.destinatarioNombre).strip() or None
                if payload.telefonoDestino is not None:
                    entrega_actual.telefonoDestino = str(payload.telefonoDestino).strip() or None
                if payload.direccion is not None:
                    entrega_actual.direccion = str(payload.direccion).strip() or None
                if payload.barrioNombre is not None:
                    entrega_actual.barrioNombre = str(payload.barrioNombre).strip() or None
                    entrega_actual.tipoEntrega = _normalize_delivery_type_from_barrio_name(entrega_actual.barrioNombre)
                    barrio_actualizado = _find_barrio_by_name(
                        db,
                        empresa_id=int(pedido.empresaID),
                        sucursal_id=int(pedido.sucursalID),
                        barrio_nombre=entrega_actual.barrioNombre,
                    )
                    entrega_actual.barrioID = int(barrio_actualizado.idBarrio) if barrio_actualizado else None
                    domicilio_recalculado = _resolve_entrega_domicilio_amount(
                        db, pedido=pedido, entrega=entrega_actual
                    )
                    _apply_pedido_domicilio_amounts(
                        pedido,
                        resolved_domicilio=domicilio_recalculado,
                        prefer_resolved=True,
                    )
                    needs_totals_recalc = True
                if payload.latitudDestino is not None:
                    entrega_actual.latitudDestino = payload.latitudDestino
                if payload.longitudDestino is not None:
                    entrega_actual.longitudDestino = payload.longitudDestino
                if payload.firma is not None:
                    entrega_actual.firma = str(payload.firma).strip() or None
                if payload.mensajeTarjeta is not None:
                    entrega_actual.mensaje = str(payload.mensajeTarjeta).strip() or None
                if payload.observacionGeneral is not None:
                    entrega_actual.observacionGeneral = str(payload.observacionGeneral).strip() or None
                if observaciones_personalizadas_payload is not missing_payload:
                    entrega_actual.observaciones = str(observaciones_personalizadas_payload or "").strip() or None
                if payload.fechaEntrega is not None:
                    fecha_base = entrega_actual.fechaEntregaProgramada or entrega_actual.fechaEntrega
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
                        produccion.updatedAt = colombia_now_naive()

        missing_financial = object()

        domicilio_payload = _payload_field_value(payload, "domicilio", missing_financial)
        costo_domicilio_payload = _payload_field_value(payload, "costoDomicilio", missing_financial)
        if costo_domicilio_payload is missing_financial:
            costo_domicilio_payload = _payload_field_value(payload, "costo_domicilio", missing_financial)
        domicilio_original_payload = _payload_field_value(payload, "domicilioOriginal", missing_financial)
        descuento_domicilio_payload = _payload_field_value(payload, "descuentoDomicilio", missing_financial)
        domicilio_obsequiado_payload = _payload_field_value(payload, "domicilioObsequiado", missing_financial)
        if domicilio_obsequiado_payload is missing_financial:
            domicilio_obsequiado_payload = _payload_field_value(payload, "domicilio_obsequiado", missing_financial)
        omitir_costo_domicilio_payload = _payload_field_value(payload, "omitirCostoDomicilio", missing_financial)
        if omitir_costo_domicilio_payload is missing_financial:
            omitir_costo_domicilio_payload = _payload_field_value(payload, "omitir_costo_domicilio", missing_financial)
        forzar_recalculo_payload = _payload_field_value(payload, "forzarRecalculoFinanciero", missing_financial)

        if any(
            value is not missing_financial
            for value in (
                domicilio_payload,
                costo_domicilio_payload,
                domicilio_original_payload,
                descuento_domicilio_payload,
                domicilio_obsequiado_payload,
                omitir_costo_domicilio_payload,
                forzar_recalculo_payload,
            )
        ):
            if entrega_actual is None:
                entrega_actual = (
                    db.query(Entrega)
                    .filter(
                        Entrega.pedidoID == pedido_id,
                        Entrega.empresaID == int(pedido.empresaID),
                    )
                    .order_by(Entrega.intentoNumero.desc(), Entrega.idEntrega.desc())
                    .first()
                )
            if domicilio_obsequiado_payload is not missing_financial:
                domicilio_obsequiado_value = bool(domicilio_obsequiado_payload)
            else:
                domicilio_obsequiado_value = None
            if omitir_costo_domicilio_payload is not missing_financial:
                omitir_costo_domicilio_value = bool(omitir_costo_domicilio_payload)
            else:
                omitir_costo_domicilio_value = None

            domicilio_cobrado_payload = (
                costo_domicilio_payload
                if costo_domicilio_payload not in (missing_financial, None)
                else domicilio_payload
            )
            resolved_domicilio = _resolve_entrega_domicilio_amount(db, pedido=pedido, entrega=entrega_actual)
            prefer_resolved = bool(
                payload.barrioNombre is not None
                or (forzar_recalculo_payload is not missing_financial and forzar_recalculo_payload)
            )
            _apply_pedido_domicilio_amounts(
                pedido,
                resolved_domicilio=resolved_domicilio,
                domicilio_cobrado=(
                    domicilio_cobrado_payload
                    if domicilio_cobrado_payload not in (missing_financial, None)
                    else None
                ),
                domicilio_original=(
                    domicilio_original_payload
                    if domicilio_original_payload not in (missing_financial, None)
                    else None
                ),
                descuento_domicilio=(
                    descuento_domicilio_payload
                    if descuento_domicilio_payload not in (missing_financial, None)
                    else None
                ),
                domicilio_obsequiado=domicilio_obsequiado_value,
                omitir_costo_domicilio=omitir_costo_domicilio_value,
                prefer_resolved=prefer_resolved,
            )

            needs_totals_recalc = True

        if needs_totals_recalc:
            db.flush()
            _recalculate_pedido_financials(
                db,
                pedido=pedido,
                aplica_iva=_normalize_ident_type(cliente.tipoIdent) == "NIT",
            )
            _sync_existing_pago_total(db, pedido=pedido)
            _invalidate_factura_impresa(db, pedido_id=int(pedido.idPedido), empresa_id=int(pedido.empresaID))

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
                    detail={"code": "FLORA_CHANNEL_REQUIRED", "message": f"{channel_field['titulo'] or 'Canal de venta'} es obligatorio"},
                )
            if canal_flora and allowed_channels and canal_flora not in allowed_channels:
                raise HTTPException(
                    status_code=400,
                    detail={"code": "FLORA_CHANNEL_INVALID", "message": f"{channel_field['titulo'] or 'Canal de venta'} inválido"},
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
                domicilio=(
                    Decimal("0.00")
                    if _pedido_omite_costo_domicilio(pedido)
                    else Decimal(str(getattr(pedido, "costoDomicilio", 0) or 0))
                ),
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
            caja_service.refresh_caja_por_pedido(
                db,
                pedido=pedido,
                usuario_id=(int(getattr(auth, "userID", 0)) if getattr(auth, "userID", None) is not None else None),
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

        missing_payload = object()
        producto_precio_payload = _payload_producto_precio_value(payload, missing_payload)

        if _is_custom_producto(producto):
            if producto_precio_payload in (missing_payload, None):
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": "PEDIDO_PRECIO_SOLO_PERSONALIZADO",
                        "message": "Debes indicar un precio válido para el arreglo personalizado.",
                    },
                )
            precio_unitario = _quantize_peso_entero(producto_precio_payload)
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
        assert_same_empresa(auth, int(pedido.empresaID))

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
    sucursal = (
        db.query(Sucursal)
        .filter(
            Sucursal.idSucursal == int(pedido.sucursalID),
            Sucursal.empresaID == int(pedido.empresaID),
        )
        .first()
    )
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
        .options(
            load_only(
                Producto.idProducto,
                Producto.empresaID,
                Producto.nombreProducto,
            )
        )
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
    empresa_titulo, empresa_subtitulo = _factura_empresa_labels(empresa, sucursal, int(pedido.empresaID))
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
    # Titulo real configurado por empresa para el canal de venta (ver empresa_menu / sql/alter_empresa_menu.sql).
    # Para Flora esta sembrado como "Celular Flora"; otras empresas ven su propio titulo si lo configuran.
    canal_venta_field = _load_empresa_menu_config(db, empresa_id=int(pedido.empresaID)).get("pedido_canal_venta")
    canal_venta_titulo = str(canal_venta_field["titulo"]).strip() if canal_venta_field else None
    canal_venta_valor = str(pago_resumen.get("canalFlora") or "No especificada").strip() or "No especificada"

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
        *([empresa_subtitulo] if empresa_subtitulo else []),
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
        *( [f"Saldo a favor: {_money_cop(saldo_favor_monto)}"] if saldo_favor_monto > 0 else [] ),
        *( [f"Nota saldo a favor: {saldo_favor_nota}"] if saldo_favor_nota else [] ),
        f"Total: {_money_cop(pedido.totalNeto)}",
        "----------------------------------------",
        f"Operador: {operador_nombre}",
        *([f"{canal_venta_titulo}: {canal_venta_valor}"] if canal_venta_field else []),
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
    estados_contables = ["APROBADO", "PAGADO", "CANCELADO", "RECHAZADO"]
    order_query = (
        db.query(Pedido, EstadoPedido)
        .join(EstadoPedido, EstadoPedido.idEstadoPedido == Pedido.estadoPedidoID)
        .filter(
            Pedido.empresaID == int(empresa_id),
            Pedido.fechaPedido >= datetime.combine(fecha_desde, datetime.min.time()),
            Pedido.fechaPedido <= datetime.combine(fecha_hasta, datetime.max.time()),
            func.upper(EstadoPedido.nombreEstado).in_(estados_contables),
        )
    )
    if sucursal_id is not None:
        order_query = order_query.filter(Pedido.sucursalID == int(sucursal_id))

    order_rows = order_query.order_by(Pedido.fechaPedido.asc(), Pedido.idPedido.asc()).all()
    pedido_ids = [int(pedido.idPedido) for pedido, _ in order_rows]
    if not pedido_ids:
        return {"orderRows": [], "arrangementRows": [], "paymentAccountRows": [], "accountingDetailRows": []}

    cliente_ids = [int(pedido.clienteID) for pedido, _ in order_rows if pedido.clienteID is not None]
    cliente_rows = (
        db.query(Cliente)
        .filter(Cliente.empresaID == int(empresa_id), Cliente.idCliente.in_(cliente_ids))
        .all()
        if cliente_ids
        else []
    )
    cliente_por_id = {int(cliente.idCliente): cliente for cliente in cliente_rows}

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

    entrega_obs_rows = (
        db.query(Entrega.pedidoID, Entrega.observacionGeneral, Entrega.observaciones)
        .filter(Entrega.empresaID == int(empresa_id), Entrega.pedidoID.in_(pedido_ids))
        .all()
    )
    entrega_obs_por_pedido: dict[int, list[str]] = {}
    for entrega_pedido_id, observacion_general, observaciones in entrega_obs_rows:
        bucket = entrega_obs_por_pedido.setdefault(int(entrega_pedido_id), [])
        for value in (observacion_general, observaciones):
            cleaned = str(value or "").strip()
            if cleaned:
                bucket.append(cleaned)

    pagos_por_pedido = _load_pago_resumen_batch(db, empresa_id=int(empresa_id), pedido_ids=pedido_ids)
    _ensure_pedido_auditoria_table(db)
    auditoria_rows = db.execute(
        text(
            """
            SELECT DISTINCT ON (pa.pedido_id)
              pa.pedido_id,
              pa.actor_login
            FROM petalops.pedido_auditoria pa
            WHERE pa.empresa_id = :empresa_id
              AND pa.pedido_id = ANY(:pedido_ids)
              AND pa.accion IN ('APROBAR_PEDIDO', 'APROBAR_PEDIDO_PIPELINE', 'GUARDAR_PEDIDO', 'CAMBIAR_ESTADO_PEDIDO')
            ORDER BY pa.pedido_id, pa.created_at DESC, pa.id_audit DESC
            """
        ),
        {"empresa_id": int(empresa_id), "pedido_ids": pedido_ids},
    ).mappings().all()
    usuario_por_pedido = {
        int(row["pedido_id"]): str(row.get("actor_login") or "system").strip() or "system"
        for row in auditoria_rows
        if row.get("pedido_id") is not None
    }

    resumen_por_fecha: dict[str, dict] = {}
    arreglos_map: dict[str, dict] = {}
    cuentas_map: dict[str, dict] = {}
    detalles_contables: list[dict] = []
    total_recaudo_global = Decimal("0.00")
    mostrar_codigo_catalogo = _mostrar_codigo_catalogo(db, empresa_id)

    for pedido, estado in order_rows:
        pedido_id = int(pedido.idPedido)
        fecha_key = _fecha_pedido_str(pedido.fechaPedido) or "Sin fecha"
        pago_resumen = pagos_por_pedido.get(pedido_id, {})
        estado_nombre = str(estado.nombreEstado if estado else "SIN_ESTADO").strip().upper()
        es_cancelado = estado_nombre in {"CANCELADO", "RECHAZADO"}
        subtotal = Decimal(str(pedido.totalBruto or 0))
        iva = Decimal(str(pedido.totalIva or 0))
        domicilio = Decimal(str(_pedido_domicilio_valor(pedido)))
        total = Decimal(str(pedido.totalNeto or 0))
        recargos = Decimal(str(pago_resumen.get("recargoLinkMonto") or 0))
        descuentos = Decimal(str(pago_resumen.get("descuentoMonto") or 0))
        saldo_favor = Decimal(str(pago_resumen.get("saldoFavorMonto") or 0))
        descuento_nota = str(pago_resumen.get("descuentoNota") or "").strip()
        saldo_favor_nota = str(pago_resumen.get("saldoFavorNota") or "").strip()
        payment_entries = pago_resumen.get("detallePago") or []
        if not payment_entries:
            metodo_pago = str(pago_resumen.get("metodoPago") or "").strip()
            if metodo_pago:
                payment_entries = [{"metodo": metodo_pago, "monto": float(total)}]
        cuentas_pago = []
        for entry in payment_entries:
            cuenta = str(entry.get("metodo") or entry.get("metodoPago") or entry.get("nombre") or "").strip()
            if cuenta:
                cuentas_pago.append(cuenta)
        cuenta_pago = " | ".join(dict.fromkeys(cuentas_pago)) or "Sin especificar"
        efectivo = Decimal("0.00")
        for entry in payment_entries:
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
            "totalSaldoFavor": Decimal("0.00"),
            "totalVenta": Decimal("0.00"),
            "totalEfectivo": Decimal("0.00"),
            "pedidosCancelados": 0,
        }
        current["cantidadPedidos"] += 1
        if es_cancelado:
            current["pedidosCancelados"] += 1
        else:
            current["totalArreglos"] += subtotal + iva
            current["totalDomicilios"] += domicilio
            current["totalRecargos"] += recargos
            current["totalVenta"] += total
            current["totalEfectivo"] += efectivo
        current["totalDescuentos"] += descuentos
        current["totalSaldoFavor"] += saldo_favor
        resumen_por_fecha[fecha_key] = current

        observaciones_pedido = []
        for detalle, _producto in detalles_por_pedido.get(pedido_id, []):
            observacion_detalle = str(getattr(detalle, "observacionesPersonalizados", "") or "").strip()
            if observacion_detalle:
                observaciones_pedido.append(observacion_detalle)
        observaciones_pedido.extend(entrega_obs_por_pedido.get(pedido_id, []))

        detalles_contables.append({
            "pedidoID": pedido_id,
            "numeroPedido": _numero_pedido_valor(pedido),
            "codigoPedido": str(pedido.codigoPedido or "").strip() or None,
            "fecha": fecha_key,
            "usuarioSistema": usuario_por_pedido.get(pedido_id, "system"),
            "cliente": str(getattr(cliente_por_id.get(int(pedido.clienteID or 0)), "nombreCompleto", "") or "Cliente"),
            "cuentaPago": cuenta_pago,
            "estado": estado_nombre,
            "cancelado": bool(es_cancelado),
            "notaCancelacion": str(pedido.motivoRechazo or "").strip() or None,
            "descuentoMonto": float(descuentos.quantize(Decimal("0.01"))),
            "descuentoNota": descuento_nota or None,
            "saldoFavorMonto": float(saldo_favor.quantize(Decimal("0.01"))),
            "saldoFavorNota": saldo_favor_nota or None,
            "observaciones": " | ".join(dict.fromkeys(observaciones_pedido)) or None,
            "totalVenta": float(total.quantize(Decimal("0.01"))),
        })

        for detalle, producto in detalles_por_pedido.get(pedido_id, []):
            codigo = _codigo_producto_visible(producto, mostrar_codigo_catalogo) or ""
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
                "totalSaldoFavor": float(item["totalSaldoFavor"].quantize(Decimal("0.01"))),
                "totalVenta": float(item["totalVenta"].quantize(Decimal("0.01"))),
                "totalEfectivo": float(item["totalEfectivo"].quantize(Decimal("0.01"))),
                "pedidosCancelados": int(item["pedidosCancelados"]),
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
        "accountingDetailRows": detalles_contables,
    }


def _build_ventas_diario_rows(
    order_rows: list[tuple[Pedido, EstadoPedido]],
    pagos_por_pedido: dict[int, dict],
) -> dict:
    resumen_por_fecha: dict[str, dict] = {}

    for pedido, estado in order_rows:
        estado_nombre = str(estado.nombreEstado if estado else "SIN_ESTADO").strip().upper()
        if estado_nombre != "APROBADO":
            continue

        pedido_id = int(pedido.idPedido)
        fecha_key = _fecha_pedido_str(pedido.fechaPedido) or "Sin fecha"
        pago_resumen = pagos_por_pedido.get(pedido_id, {})

        total_arreglos = (
            Decimal(str(pedido.totalBruto or 0))
            + Decimal(str(pedido.totalIva or 0))
        ).quantize(Decimal("0.01"))
        total_domicilios = Decimal(str(pedido.costoDomicilio or 0)).quantize(Decimal("0.01"))
        total_recargos = Decimal(str(pago_resumen.get("recargoLinkMonto") or 0)).quantize(Decimal("0.01"))
        total_descuentos = Decimal(str(pago_resumen.get("descuentoMonto") or 0)).quantize(Decimal("0.01"))
        total_saldo_favor = Decimal(str(pago_resumen.get("saldoFavorMonto") or 0)).quantize(Decimal("0.01"))
        total_venta = (
            total_arreglos
            + total_domicilios
            + total_recargos
            - total_descuentos
            + total_saldo_favor
        ).quantize(Decimal("0.01"))

        current = resumen_por_fecha.get(fecha_key) or {
            "fecha": fecha_key,
            "cantidadPedidos": 0,
            "totalArreglos": Decimal("0.00"),
            "totalDomicilios": Decimal("0.00"),
            "totalRecargos": Decimal("0.00"),
            "totalDescuentos": Decimal("0.00"),
            "totalSaldoFavor": Decimal("0.00"),
            "totalVenta": Decimal("0.00"),
        }
        current["cantidadPedidos"] += 1
        current["totalArreglos"] += total_arreglos
        current["totalDomicilios"] += total_domicilios
        current["totalRecargos"] += total_recargos
        current["totalDescuentos"] += total_descuentos
        current["totalSaldoFavor"] += total_saldo_favor
        current["totalVenta"] += total_venta
        resumen_por_fecha[fecha_key] = current

    order_rows_payload = sorted(
        [
            {
                "fecha": item["fecha"],
                "cantidadPedidos": int(item["cantidadPedidos"]),
                "totalArreglos": float(item["totalArreglos"].quantize(Decimal("0.01"))),
                "totalDomicilios": float(item["totalDomicilios"].quantize(Decimal("0.01"))),
                "totalRecargos": float(item["totalRecargos"].quantize(Decimal("0.01"))),
                "totalDescuentos": float(item["totalDescuentos"].quantize(Decimal("0.01"))),
                "totalSaldoFavor": float(item["totalSaldoFavor"].quantize(Decimal("0.01"))),
                "totalVenta": float(item["totalVenta"].quantize(Decimal("0.01"))),
            }
            for item in resumen_por_fecha.values()
        ],
        key=lambda item: item["fecha"],
    )
    totals = {
        "fecha": "Totales",
        "cantidadPedidos": sum(int(item["cantidadPedidos"]) for item in order_rows_payload),
        "totalArreglos": float(sum(Decimal(str(item["totalArreglos"])) for item in order_rows_payload).quantize(Decimal("0.01"))),
        "totalDomicilios": float(sum(Decimal(str(item["totalDomicilios"])) for item in order_rows_payload).quantize(Decimal("0.01"))),
        "totalRecargos": float(sum(Decimal(str(item["totalRecargos"])) for item in order_rows_payload).quantize(Decimal("0.01"))),
        "totalDescuentos": float(sum(Decimal(str(item["totalDescuentos"])) for item in order_rows_payload).quantize(Decimal("0.01"))),
        "totalSaldoFavor": float(sum(Decimal(str(item["totalSaldoFavor"])) for item in order_rows_payload).quantize(Decimal("0.01"))),
        "totalVenta": float(sum(Decimal(str(item["totalVenta"])) for item in order_rows_payload).quantize(Decimal("0.01"))),
    }
    return {"orderRows": order_rows_payload, "totals": totals}


@router.get("/contabilidad/ventas-diario", dependencies=[Depends(require_module_access("contabilidad", "puedeVer"))])
@router.get("/pedidos/contabilidad/ventas-diario", dependencies=[Depends(require_module_access("contabilidad", "puedeVer"))])
def resumen_ventas_diario(
    empresa_id: int = Query(..., alias="empresaID"),
    sucursal_id: int | None = Query(None, alias="sucursalID"),
    fecha_desde: date = Query(..., alias="fechaDesde"),
    fecha_hasta: date = Query(..., alias="fechaHasta"),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, int(empresa_id))
    if fecha_desde > fecha_hasta:
        raise HTTPException(status_code=400, detail="fechaDesde no puede ser mayor que fechaHasta")

    order_query = (
        db.query(Pedido, EstadoPedido)
        .join(EstadoPedido, EstadoPedido.idEstadoPedido == Pedido.estadoPedidoID)
        .filter(
            Pedido.empresaID == int(empresa_id),
            Pedido.fechaPedido >= datetime.combine(fecha_desde, datetime.min.time()),
            Pedido.fechaPedido < datetime.combine(fecha_hasta, datetime.min.time()) + timedelta(days=1),
            func.upper(EstadoPedido.nombreEstado) == "APROBADO",
        )
    )
    if sucursal_id is not None:
        order_query = order_query.filter(Pedido.sucursalID == int(sucursal_id))

    order_rows = order_query.order_by(Pedido.fechaPedido.asc(), Pedido.idPedido.asc()).all()
    pedido_ids = [int(pedido.idPedido) for pedido, _ in order_rows]
    pagos_por_pedido = (
        _load_pago_resumen_batch(db, empresa_id=int(empresa_id), pedido_ids=pedido_ids)
        if pedido_ids
        else {}
    )
    return _build_ventas_diario_rows(order_rows, pagos_por_pedido)


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
    cancelacion_operativa = _sincronizar_cancelacion_operativa_desde_pedido(
        db,
        pedido,
        motivo=pedido.motivoRechazo,
    )
    _audit_pedido_action(
        db=db,
        actor=auth,
        pedido=pedido,
        accion=("CANCELAR_PEDIDO_APROBADO" if es_aprobado else "RECHAZAR_PEDIDO"),
        estado_origen_id=estado_origen_id,
        estado_destino_id=int(estado_rechazado.idEstadoPedido),
        extra={"motivo": pedido.motivoRechazo},
    )
    caja_service.refresh_caja_por_pedido(
        db,
        pedido=pedido,
        usuario_id=(int(getattr(auth, "userID", 0)) if getattr(auth, "userID", None) is not None else None),
    )
    db.commit()

    return {
        "status": "ok",
        "pedidoID": pedido_id,
        "estado": str(estado_rechazado.nombreEstado),
        "motivo": pedido.motivoRechazo,
        "cancelacionOperativa": cancelacion_operativa,
    }


@router.post("/pedido/checkout", response_model=PedidoCheckoutResponse, dependencies=[Depends(require_module_access("pedidos", "puedeCrear"))])
@limiter.limit(rate_limit("pedido_checkout", "60/minute"))
def checkout(request: Request, data: PedidoCheckoutRequest, db: Session = Depends(get_db), auth=Depends(get_current_auth_context)):
    """Endpoint de checkout: delega la lógica transaccional al servicio de pedidos."""
    assert_same_empresa(auth, int(data.empresaID))
    result = checkout_pedido(db=db, payload=data)
    pedido_id = int(result.get("pedidoID") or 0)
    pedido = db.query(Pedido).filter(Pedido.idPedido == pedido_id, Pedido.empresaID == int(data.empresaID)).first()
    if pedido:
        _audit_pedido_action(
            db=db,
            actor=auth,
            pedido=pedido,
            accion="CREAR_PEDIDO_CHECKOUT",
            estado_origen_id=None,
            estado_destino_id=int(pedido.estadoPedidoID) if pedido.estadoPedidoID is not None else None,
            extra={
                "numeroPedido": int(pedido.numeroPedido or 0),
                "codigoPedido": str(pedido.codigoPedido or "").strip() or None,
                "total": float(pedido.totalNeto or 0),
            },
        )
        db.commit()
    return result


@router.post("/pedido/manual", response_model=PedidoManualResponse, dependencies=[Depends(require_module_access("pedidos", "puedeCrear"))])
@limiter.limit(rate_limit("pedido_manual", "60/minute"))
def crear_pedido_manual(request: Request, data: PedidoManualRequest, db: Session = Depends(get_db), auth=Depends(get_current_auth_context)):
    empresa_id = int(data.empresaID if data.empresaID is not None else data.empresaId or 0)
    sucursal_id = int(data.sucursalID if data.sucursalID is not None else data.sucursalId or 0)
    if empresa_id <= 0 or sucursal_id <= 0:
        raise HTTPException(status_code=400, detail={"code": "PEDIDO_MANUAL_SCOPE_INVALID", "message": "empresaID y sucursalID son obligatorios"})
    assert_same_empresa(auth, empresa_id)

    productos_payload = data.productos if data.productos is not None else data.items
    if not productos_payload:
        raise HTTPException(status_code=400, detail={"code": "PEDIDO_MANUAL_PRODUCTS_EMPTY", "message": "productos no puede estar vacío"})

    productos_normalizados = []
    for item in productos_payload:
        producto_id = item.productoID if item.productoID is not None else item.productoId
        if producto_id is None:
            raise HTTPException(status_code=400, detail={"code": "PEDIDO_MANUAL_PRODUCT_INVALID", "message": "Cada producto debe incluir productoID"})
        cantidad = Decimal(str(item.cantidad or 0))
        if cantidad <= 0:
            raise HTTPException(status_code=400, detail={"code": "PEDIDO_MANUAL_QUANTITY_INVALID", "message": "cantidad debe ser mayor que 0"})
        precio = item.productoPrecio if item.productoPrecio is not None else item.precioUnitario
        productos_normalizados.append(
            {
                "productoID": int(producto_id),
                "cantidad": cantidad,
                "precio": (_round_money_decimal(Decimal(str(precio))) if precio is not None else None),
                "observaciones": item.productoObservaciones if item.productoObservaciones is not None else item.observaciones,
            }
        )

    producto_ids = list({item["productoID"] for item in productos_normalizados})

    try:
        estado_inicial = _buscar_estado_inicial_pedido(db)
        if not estado_inicial:
            raise HTTPException(status_code=400, detail="No existe un estado inicial activo 'CREADO' o 'PENDIENTE'")

        productos_db = (
            db.query(Producto)
            .filter(
                Producto.idProducto.in_(producto_ids),
                _activo_truthy(Producto.activo),
                Producto.empresaID == empresa_id,
            )
            .all()
        )
        productos_map = {int(producto.idProducto): producto for producto in productos_db}
        if len(productos_map) != len(producto_ids):
            raise HTTPException(status_code=400, detail={"code": "PEDIDO_MANUAL_PRODUCT_NOT_FOUND", "message": "Uno o más productos no existen o están inactivos"})

        cliente_id_payload = data.cliente.clienteID if data.cliente.clienteID is not None else data.cliente.clienteId
        if cliente_id_payload is not None:
            cliente = (
                db.query(Cliente)
                .filter(
                    Cliente.idCliente == int(cliente_id_payload),
                    Cliente.empresaID == empresa_id,
                )
                .first()
            )
            if not cliente:
                raise HTTPException(status_code=404, detail={"code": "CLIENTE_NOT_FOUND", "message": "Cliente no encontrado"})
            cliente_nombre_payload = str(data.cliente.nombreCompleto or data.cliente.nombres or "").strip()
            if cliente_nombre_payload:
                cliente.nombreCompleto = cliente_nombre_payload
            if data.cliente.telefono is not None:
                cliente.telefono = str(data.cliente.telefono).strip() or cliente.telefono
                cliente.telefonoCompleto = (
                    _normalizar_telefono_completo_pedido(data.cliente.indicativo or cliente.indicativo, cliente.telefono)
                    or cliente.telefonoCompleto
                )
            if data.cliente.email is not None:
                cliente.email = data.cliente.email
            if data.cliente.tipoIdent is not None:
                cliente.tipoIdent = _normalize_ident_type(data.cliente.tipoIdent) or cliente.tipoIdent
            if data.cliente.identificacion is not None:
                cliente.identificacion = str(data.cliente.identificacion).strip() or cliente.identificacion
            if data.cliente.indicativo is not None:
                cliente.indicativo = data.cliente.indicativo
            cliente.updatedAt = colombia_now_naive()
            db.flush()
        else:
            cliente_nombre = str(data.cliente.nombreCompleto or data.cliente.nombres or "").strip()
            telefono_cliente = str(data.cliente.telefono or "").strip()
            if not cliente_nombre:
                raise HTTPException(status_code=400, detail={"code": "PEDIDO_MANUAL_CLIENT_NAME_REQUIRED", "message": "El nombre del cliente es obligatorio"})
            if not telefono_cliente:
                raise HTTPException(status_code=400, detail={"code": "PEDIDO_MANUAL_CLIENT_PHONE_REQUIRED", "message": "El teléfono del cliente es obligatorio"})
            cliente = _upsert_cliente_pedido_manual(
                db,
                empresa_id=empresa_id,
                tipo_ident=_normalize_ident_type(data.cliente.tipoIdent) or "CC",
                identificacion=data.cliente.identificacion,
                indicativo=data.cliente.indicativo,
                nombre_completo=cliente_nombre,
                telefono=telefono_cliente,
                email=data.cliente.email,
            )

        entrega_barrio_id = data.entrega.barrioID if data.entrega.barrioID is not None else data.entrega.barrioId
        tipo_entrega = data.entrega.tipoEntrega or _normalize_delivery_type_from_barrio_name(data.entrega.barrioNombre)
        domicilio_resuelto = _resolve_costo_domicilio(
            db,
            empresa_id=empresa_id,
            sucursal_id=sucursal_id,
            tipo_entrega=tipo_entrega,
            barrio_id=(int(entrega_barrio_id) if entrega_barrio_id is not None else None),
            barrio_nombre=data.entrega.barrioNombre,
        )
        domicilio_amounts = _manual_domicilio_amounts(
            domicilio=data.domicilio,
            domicilio_original=data.domicilioOriginal,
            descuento_domicilio=data.descuentoDomicilio,
            domicilio_obsequiado=bool(data.domicilioObsequiado),
            omitir_costo_domicilio=bool(data.omitirCostoDomicilio),
            resolved_domicilio=domicilio_resuelto,
        )

        fecha_pedido = colombia_now_naive()
        pedido = Pedido(
            empresaID=empresa_id,
            sucursalID=sucursal_id,
            numeroPedido=_numero_pedido_temporal(),
            codigoPedido=None,
            clienteID=int(cliente.idCliente),
            fechaPedido=fecha_pedido,
            estadoPedidoID=int(estado_inicial.idEstadoPedido),
            totalBruto=Decimal("0.00"),
            totalIva=Decimal("0.00"),
            costoDomicilio=domicilio_amounts["cobrado"],
            domicilioObsequiado=bool(domicilio_amounts["domicilioObsequiado"]),
            omitirCostoDomicilio=bool(domicilio_amounts["omitirCostoDomicilio"]),
            domicilioOriginal=domicilio_amounts["original"],
            descuentoDomicilio=domicilio_amounts["descuento"],
            totalNeto=Decimal("0.00"),
            createdAt=fecha_pedido,
        )
        db.add(pedido)
        db.flush()
        pedido.numeroPedido = -int(pedido.idPedido)

        total_bruto = Decimal("0.00")
        for item in productos_normalizados:
            producto = productos_map[int(item["productoID"])]
            precio_unitario = item["precio"] or _find_branch_product_price(
                db,
                empresa_id=empresa_id,
                sucursal_id=sucursal_id,
                producto_id=int(producto.idProducto),
            )
            cantidad = Decimal(str(item["cantidad"]))
            subtotal = (precio_unitario * cantidad).quantize(Decimal("0.01"))
            total_bruto += subtotal
            db.add(
                PedidoDetalle(
                    empresaID=empresa_id,
                    sucursalID=sucursal_id,
                    pedidoID=int(pedido.idPedido),
                    productoID=int(producto.idProducto),
                    cantidad=cantidad,
                    precioUnitario=precio_unitario,
                    ivaUnitario=Decimal("0.00"),
                    subtotal=subtotal,
                    observacionesPersonalizados=_sanitize_producto_observacion(item["observaciones"], producto),
                )
            )

        pedido.totalBruto = total_bruto.quantize(Decimal("0.01"))
        pedido.totalIva = Decimal("0.00")
        pedido.totalNeto = (pedido.totalBruto + pedido.totalIva + Decimal(str(pedido.costoDomicilio or 0))).quantize(Decimal("0.01"))

        fecha_entrega = data.entrega.fechaEntrega
        if isinstance(fecha_entrega, datetime):
            fecha_entrega_dt = fecha_entrega
        elif fecha_entrega:
            fecha_entrega_dt = _parse_iso_date(str(fecha_entrega))
        else:
            fecha_entrega_dt = fecha_pedido

        db.add(
            Entrega(
                empresaID=empresa_id,
                sucursalID=sucursal_id,
                pedidoID=int(pedido.idPedido),
                estadoEntregaID=1,
                tipoEntrega=tipo_entrega,
                destinatario=data.entrega.destinatario or data.entrega.destinatarioNombre,
                telefonoDestino=data.entrega.telefonoDestino,
                direccion=data.entrega.direccion,
                barrioID=(int(entrega_barrio_id) if entrega_barrio_id is not None else None),
                barrioNombre=data.entrega.barrioNombre,
                rangoHora=data.entrega.rangoHora or data.entrega.horaEntrega,
                mensaje=data.entrega.mensaje if data.entrega.mensaje is not None else data.entrega.mensajeTarjeta,
                firma=data.entrega.firma,
                observacionGeneral=data.entrega.observacionGeneral,
                fechaEntregaProgramada=fecha_entrega_dt,
                fechaEntrega=fecha_entrega_dt,
                latitudDestino=data.entrega.latitudDestino,
                longitudDestino=data.entrega.longitudDestino,
                intentoNumero=1,
                createdAt=fecha_pedido,
            )
        )

        _audit_pedido_action(
            db=db,
            actor=auth,
            pedido=pedido,
            accion="CREAR_PEDIDO_MANUAL",
            estado_origen_id=None,
            estado_destino_id=int(estado_inicial.idEstadoPedido),
            extra={
                "total": float(pedido.totalNeto or 0),
                "cantidadProductos": len(productos_normalizados),
            },
        )
        db.commit()
        total_general = Decimal(str(pedido.totalNeto or 0)).quantize(Decimal("0.01"))
        return {
            "pedidoID": int(pedido.idPedido),
            "numeroPedido": None,
            "codigoPedido": None,
            "pedidoIDs": [int(pedido.idPedido)],
            "cantidadPedidos": 1,
            "total": float(total_general),
            "estado": str(estado_inicial.nombreEstado or "CREADO"),
            "domicilioObsequiado": bool(pedido.domicilioObsequiado),
            "omitirCostoDomicilio": bool(pedido.omitirCostoDomicilio),
            "domicilio": float(pedido.costoDomicilio or 0),
            "domicilioOriginal": float(pedido.domicilioOriginal or 0),
            "descuentoDomicilio": float(pedido.descuentoDomicilio or 0),
        }
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error registrando pedido manual: {exc}")


@router.post("/pedido", dependencies=[Depends(require_module_access("pedidos", "puedeCrear"))])
@limiter.limit(rate_limit("pedido_crear", "60/minute"))
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
            createdAt=colombia_now_naive(),
        )

        db.add(cliente)
        db.flush()  # obtiene idCliente sin commit

        # 4️⃣ Crear pedido
        fecha_pedido = colombia_now_naive()

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
            createdAt=colombia_now_naive(),
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
                subtotal=(precio_unitario * cantidad).quantize(Decimal("0.01")),
                observacionesPersonalizados=None,
            )

            db.add(detalle)

        _audit_pedido_action(
            db=db,
            actor=auth,
            pedido=pedido,
            accion="CREAR_PEDIDO_LEGACY",
            estado_origen_id=None,
            estado_destino_id=int(estado_inicial.idEstadoPedido),
            extra={
                "total": float(pedido.totalNeto or 0),
                "cantidadProductos": len(data.items),
            },
        )
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
    cancelacion_operativa = None
    producciones_estado_5 = 0
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
    elif str(estado_destino.nombreEstado or "").strip().upper() in {"CANCELADO", "RECHAZADO"}:
        cancelacion_operativa = _sincronizar_cancelacion_operativa_desde_pedido(
            db,
            pedido,
            motivo=pedido.motivoRechazo,
        )
        producciones_estado_5 = int(cancelacion_operativa.get("produccionesCanceladas", 0))

    if str(estado_destino.nombreEstado or "").strip().upper() in {"CANCELADO", "RECHAZADO"}:
        _audit_pedido_action(
            db=db,
            actor=auth,
            pedido=pedido,
            accion="CANCELAR_PEDIDO_PIPELINE",
            estado_origen_id=int(estado_actual),
            estado_destino_id=int(nuevo_estado_id),
            extra={"motivo": pedido.motivoRechazo},
        )
    elif str(estado_destino.nombreEstado or "").strip().upper() not in {"APROBADO", "PAGADO"}:
        _audit_pedido_action(
            db=db,
            actor=auth,
            pedido=pedido,
            accion="CAMBIAR_ESTADO_PEDIDO",
            estado_origen_id=int(estado_actual),
            estado_destino_id=int(nuevo_estado_id),
        )

    db.commit()

    return {
        "status": "ok",
        "nuevoEstado": nuevo_estado_id,
        "produccion": produccion,
        "produccionesEstado5": int(producciones_estado_5),
        "cancelacionOperativa": cancelacion_operativa,
    }
