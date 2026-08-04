from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, cast, func, or_, text
from sqlalchemy.orm import Session, aliased, load_only

from app.core.logger import get_logger
from app.core.ordering import sort_operativo
from app.core.security import assert_same_empresa, get_current_auth_context, require_module_access
from app.core.timezone import as_colombia_naive_datetime, colombia_now_naive, colombia_today
from app.database import get_db
from app.models.cliente import Cliente
from app.models.domiciliario import Domiciliario
from app.models.entrega import Entrega
from app.models.estadopedido import EstadoPedido
from app.models.pedido import Pedido
from app.models.pedidodetalle import PedidoDetalle
from app.models.producto import Producto
from app.models.produccion import Produccion
from app.models.sucursal import Sucursal
from app.schemas.pipeline import PipelinePedidoCard, PipelinePedidosResponse, PipelineStage

router = APIRouter(
    prefix="/pipeline",
    tags=["Pipeline Operativo"],
    dependencies=[Depends(require_module_access("pedidos", "puedeVer"))],
)
pipeline_logger = get_logger("pipeline")


def _err(code: str, message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "module": "pipeline"},
    )


STAGE_PROGRESS: dict[PipelineStage, int] = {
    "creado": 10,
    "aprobado": 20,
    "pendiente_produccion": 35,
    "en_produccion": 55,
    "listo": 70,
    "en_camino": 85,
    "entregado": 100,
    "cancelado": 100,
}

STAGE_COLOR: dict[PipelineStage, str] = {
    "creado": "#64748b",
    "aprobado": "#2563eb",
    "pendiente_produccion": "#7c3aed",
    "en_produccion": "#f59e0b",
    "listo": "#0ea5e9",
    "en_camino": "#ec4899",
    "entregado": "#10b981",
    "cancelado": "#ef4444",
}


def _numero_pedido(pedido: Pedido) -> int:
    if pedido.numeroPedido is not None:
        return int(pedido.numeroPedido)
    return int(pedido.idPedido)


def _hora_text(dt: datetime | None) -> str | None:
    # fechaEntregaProgramada/reprogramadaPara solo guardan la FECHA (siempre
    # quedan en 00:00) — la hora real, cuando existe, vive aparte en
    # entrega.rangoHora (texto libre tipo "Tarde (2pm-6pm)"). Mostrar "00:00"
    # aca seria mostrar un dato inventado, asi que no se devuelve nada para
    # esos casos; el llamador debe usar rango_hora en su lugar.
    if not dt or dt.time() == time.min:
        return None
    return dt.strftime("%H:%M")


_RANGO_HORA_TIME_TOKEN_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", re.IGNORECASE)


def _parse_rango_hora_deadline_time(rango_hora: str | None) -> time | None:
    """Interpreta entrega.rangoHora (texto libre) para sacar la hora limite
    real de entrega. Dos formatos existen hoy en datos reales:
      - Un rango con paréntesis, ej. "Tarde (2pm - 6pm)" o "Mañana (8am -
        12pm)" -> usa el FINAL del rango (6pm / 12pm) como limite.
      - Una hora puntual en formato 24h, ej. "14:00" (la que guarda el
        input type="time" del formulario) -> esa misma hora es el limite.
    Devuelve None si no se pudo interpretar nada util; el llamador cae de
    vuelta al fin del dia en ese caso."""
    raw = str(rango_hora or "").strip()
    if not raw:
        return None

    bracket_match = re.search(r"\(([^)]+)\)", raw)
    inner = bracket_match.group(1) if bracket_match else raw
    matches = list(_RANGO_HORA_TIME_TOKEN_RE.finditer(inner))
    if not matches:
        return None
    match = matches[-1]

    hour = int(match.group(1))
    minute = int(match.group(2)) if match.group(2) else 0
    meridiano = (match.group(3) or "").lower()

    # "00:00" sin am/pm explicito es el mismo valor por defecto que ya trae
    # la columna de fecha cuando no se eligio hora real (ver _hora_text) —
    # no es una entrega de medianoche de verdad, asi que se trata como dato
    # no interpretable en vez de fijar el limite a la medianoche del mismo
    # dia (eso volveria a marcar el pedido como atrasado apenas empieza).
    if hour == 0 and minute == 0 and not meridiano:
        return None

    if meridiano:
        hour = hour % 12
        if meridiano == "pm":
            hour += 12

    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


def _late_deadline(target: datetime | None, rango_hora: str | None = None) -> datetime | None:
    """Fecha limite efectiva para considerar un pedido atrasado. Cuando solo
    se guardo la fecha (hora en 00:00, ver _hora_text), se usa el final real
    de la ventana de entrega si rango_hora trae algo interpretable (ver
    _parse_rango_hora_deadline_time); si no, se le da el beneficio de la
    duda hasta el final de ese dia — de lo contrario CUALQUIER pedido
    programado para "hoy" aparece atrasado desde el instante en que se crea,
    porque medianoche ya quedo en el pasado apenas empieza el dia."""
    target = as_colombia_naive_datetime(target)
    if not target:
        return None
    if target.time() == time.min:
        deadline_time = _parse_rango_hora_deadline_time(rango_hora) or time.max
        return datetime.combine(target.date(), deadline_time)
    return target


def _minutes_left(target: datetime | None, rango_hora: str | None = None) -> int | None:
    deadline = _late_deadline(target, rango_hora)
    if not deadline:
        return None
    now = colombia_now_naive()
    delta = deadline - now
    return int(delta.total_seconds() // 60)


def _catalog_key(value: str | None) -> str:
    return str(value or "").strip().lower().replace("_", "").replace(" ", "")


def _resolve_stage(
    pedido_estado: str | None,
    prod_estado: int | None,
    entrega_estado: int | None,
    prod_estado_key: str | None = None,
    entrega_estado_key: str | None = None,
) -> PipelineStage:
    pedido_key = str(pedido_estado or "").strip().upper()
    if pedido_key in {"CANCELADO", "RECHAZADO"}:
        return "cancelado"

    entrega_key = _catalog_key(entrega_estado_key)
    if entrega_key == "cancelado" or (not entrega_key and entrega_estado in {6}):
        return "cancelado"
    if entrega_key == "entregado" or (not entrega_key and entrega_estado in {4}):
        return "entregado"
    if entrega_key in {"enruta", "encamino"} or (not entrega_key and entrega_estado in {3}):
        return "en_camino"

    prod_key = _catalog_key(prod_estado_key)
    if prod_key == "cancelado" or (not prod_key and prod_estado in {5}):
        return "cancelado"
    if prod_key in {"terminado", "listo", "paraentrega"} or (not prod_key and prod_estado in {4}):
        return "listo"
    if prod_key in {"asignado", "enproceso", "enproduccion"} or (not prod_key and prod_estado in {2, 3}):
        return "en_produccion"
    if prod_key == "pendiente" or (not prod_key and prod_estado in {1}):
        return "pendiente_produccion"

    if pedido_key == "CREADO":
        return "creado"
    if pedido_key in {"APROBADO", "PAGADO"}:
        return "aprobado"
    return "aprobado"

@router.get("/pedidos", response_model=PipelinePedidosResponse)
def listar_pipeline_pedidos(
    empresa_id: int = Query(..., alias="empresaID"),
    sucursal_id: int | None = Query(None, alias="sucursalID"),
    fecha: date | None = Query(None),
    fecha_desde: date | None = Query(None, alias="fechaDesde"),
    fecha_hasta: date | None = Query(None, alias="fechaHasta"),
    domiciliario_id: str | None = Query(None, alias="domiciliarioID"),
    florista_id: str | None = Query(None, alias="floristaID"),
    numero_pedido: str | None = Query(None, alias="numeroPedido"),
    solo_hoy: bool = Query(False, alias="soloHoy"),
    solo_atrasados: bool = Query(False, alias="soloAtrasados"),
    solo_en_produccion: bool = Query(False, alias="soloEnProduccion"),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    try:
        assert_same_empresa(auth, empresa_id)

        entrega_last_sq = (
            db.query(
                Entrega.pedidoID.label("pedido_id"),
                func.max(Entrega.idEntrega).label("entrega_id"),
            )
            .filter(Entrega.empresaID == empresa_id)
            .group_by(Entrega.pedidoID)
            .subquery()
        )

        prod_last_sq = (
            db.query(
                Produccion.pedidoID.label("pedido_id"),
                func.max(Produccion.idProduccion).label("produccion_id"),
            )
            .filter(Produccion.empresaID == empresa_id)
            .group_by(Produccion.pedidoID)
            .subquery()
        )

        EntregaLast = aliased(Entrega)
        ProduccionLast = aliased(Produccion)
        FloristaLast = aliased(Domiciliario)

        q = (
            db.query(Pedido, Cliente, EstadoPedido, EntregaLast, ProduccionLast, Domiciliario, FloristaLast)
            .options(
                load_only(Domiciliario.idDomiciliario, Domiciliario.empresaID, Domiciliario.nombre),
                load_only(FloristaLast.idDomiciliario, FloristaLast.empresaID, FloristaLast.nombre),
            )
            .join(Cliente, Cliente.idCliente == Pedido.clienteID)
            .outerjoin(EstadoPedido, EstadoPedido.idEstadoPedido == Pedido.estadoPedidoID)
            .outerjoin(entrega_last_sq, entrega_last_sq.c.pedido_id == Pedido.idPedido)
            .outerjoin(EntregaLast, EntregaLast.idEntrega == entrega_last_sq.c.entrega_id)
            .outerjoin(prod_last_sq, prod_last_sq.c.pedido_id == Pedido.idPedido)
            .outerjoin(ProduccionLast, ProduccionLast.idProduccion == prod_last_sq.c.produccion_id)
            .outerjoin(
                Domiciliario,
                (Domiciliario.idDomiciliario == EntregaLast.domiciliarioID)
                & (Domiciliario.empresaID == Pedido.empresaID),
            )
            .outerjoin(
                FloristaLast,
                (FloristaLast.idDomiciliario == ProduccionLast.floristaID)
                & (FloristaLast.empresaID == Pedido.empresaID),
            )
            .filter(Pedido.empresaID == empresa_id)
        )

        if sucursal_id is not None:
            q = q.filter(Pedido.sucursalID == sucursal_id)
        domiciliario_term = str(domiciliario_id or "").strip()
        if domiciliario_term:
            if domiciliario_term.isdigit():
                q = q.filter(
                    or_(
                        EntregaLast.domiciliarioID == int(domiciliario_term),
                        Domiciliario.nombre.ilike(f"%{domiciliario_term}%"),
                    )
                )
            else:
                q = q.filter(Domiciliario.nombre.ilike(f"%{domiciliario_term}%"))
        florista_term = str(florista_id or "").strip()
        if florista_term:
            if florista_term.isdigit():
                q = q.filter(
                    or_(
                        ProduccionLast.floristaID == int(florista_term),
                        FloristaLast.nombre.ilike(f"%{florista_term}%"),
                    )
                )
            else:
                q = q.filter(FloristaLast.nombre.ilike(f"%{florista_term}%"))

        if numero_pedido:
            term = f"%{numero_pedido.strip()}%"
            q = q.filter(
                or_(
                    cast(Pedido.numeroPedido, String).ilike(term),
                    cast(Pedido.idPedido, String).ilike(term),
                    func.coalesce(Pedido.codigoPedido, "").ilike(term),
                )
            )

        if fecha_desde or fecha_hasta:
            start_date = fecha_desde or fecha_hasta
            end_date = fecha_hasta or fecha_desde
            start = datetime.combine(start_date, datetime.min.time())
            end = datetime.combine(end_date, datetime.max.time())
            q = q.filter(Pedido.fechaPedido.between(start, end))
        elif fecha:
            start = datetime.combine(fecha, datetime.min.time())
            end = datetime.combine(fecha, datetime.max.time())
            q = q.filter(Pedido.fechaPedido.between(start, end))
        elif solo_hoy:
            today = colombia_today()
            start = datetime.combine(today, datetime.min.time())
            end = datetime.combine(today, datetime.max.time())
            q = q.filter(Pedido.fechaPedido.between(start, end))

        rows = q.order_by(Pedido.fechaPedido.desc(), Pedido.idPedido.desc()).all()
        pedido_ids = [int(row[0].idPedido) for row in rows]

        prod_estado_map = {
            int(row[0]): str(row[1] or "")
            for row in db.execute(
                text(
                    """
                    SELECT id_estado_produccion, lower(coalesce(codigo, nombre, ''))
                    FROM petalops.estado_produccion
                    """
                )
            ).all()
        }
        entrega_estado_map = {
            int(row[0]): str(row[1] or "")
            for row in db.execute(
                text(
                    """
                    SELECT id_estado_entrega, lower(coalesce(codigo, nombre, ''))
                    FROM petalops.estado_entrega
                    """
                )
            ).all()
        }
        productos_por_pedido: dict[int, dict[str, str | None]] = {}
        if pedido_ids:
            det_rows = db.execute(
                text(
                    """
                    SELECT
                        pd.pedido_id,
                        string_agg(p.nombre_producto, ', ' ORDER BY pd.id_pedido_detalle) AS resumen
                    FROM petalops.pedido_detalle pd
                    JOIN petalops.producto p
                      ON p.id_producto = pd.producto_id
                     AND p.empresa_id = :empresa_id
                    WHERE pd.empresa_id = :empresa_id
                      AND pd.pedido_id = ANY(:pedido_ids)
                    GROUP BY pd.pedido_id
                    """
                ),
                {"empresa_id": int(empresa_id), "pedido_ids": pedido_ids},
            ).mappings().all()
            productos_por_pedido = {
                int(row["pedido_id"]): {
                    "resumen": str(row.get("resumen") or ""),
                }
                for row in det_rows
            }

        sucursal_map: dict[int, str] = {}
        if pedido_ids:
            sucursal_ids = sorted({int(row[0].sucursalID) for row in rows if row[0].sucursalID is not None})
            if sucursal_ids:
                rows_s = (
                    db.query(Sucursal.idSucursal, Sucursal.nombreSucursal)
                    .filter(
                        Sucursal.empresaID == empresa_id,
                        Sucursal.idSucursal.in_(sucursal_ids),
                    )
                    .all()
                )
                sucursal_map = {int(sid): str(name or f"Sucursal {sid}") for sid, name in rows_s}

        board: dict[PipelineStage, list[PipelinePedidoCard]] = {
            "creado": [],
            "aprobado": [],
            "pendiente_produccion": [],
            "en_produccion": [],
            "listo": [],
            "en_camino": [],
            "entregado": [],
            "cancelado": [],
        }

        for pedido, cliente, estado_pedido, entrega, produccion, domiciliario, florista in rows:
            prod_estado_id = int(produccion.estado) if produccion and produccion.estado is not None else None
            entrega_estado_id = int(entrega.estadoEntregaID) if entrega and entrega.estadoEntregaID is not None else None
            stage = _resolve_stage(
                (estado_pedido.nombreEstado if estado_pedido else None),
                prod_estado_id,
                entrega_estado_id,
                prod_estado_map.get(prod_estado_id) if prod_estado_id is not None else None,
                entrega_estado_map.get(entrega_estado_id) if entrega_estado_id is not None else None,
            )

            if solo_en_produccion and stage != "en_produccion":
                continue

            fecha_entrega = as_colombia_naive_datetime(
                entrega.reprogramadaPara
                if entrega and entrega.reprogramadaPara
                else (entrega.fechaEntregaProgramada if entrega else None)
            )
            rango_hora_valor = (
                str(entrega.rangoHora).strip() if entrega and entrega.rangoHora and str(entrega.rangoHora).strip() else None
            )
            late_deadline = _late_deadline(fecha_entrega, rango_hora_valor)
            if solo_atrasados and (late_deadline is None or late_deadline >= colombia_now_naive()):
                continue

            prioridad = (str(produccion.prioridad or "MEDIA").upper() if produccion else "MEDIA")
            urgente = prioridad in {"ALTA", "URGENTE", "CRITICA"}
            producto_payload = productos_por_pedido.get(int(pedido.idPedido), {})
            resumen = str(producto_payload.get("resumen") or "")
            tiene_tarjeta = bool(entrega and entrega.mensaje and str(entrega.mensaje).strip())
            domiciliario_id_value = (
                int(entrega.domiciliarioID)
                if entrega and entrega.domiciliarioID is not None
                else None
            )
            florista_id_value = (
                int(produccion.floristaID)
                if produccion and produccion.floristaID is not None
                else None
            )

            card = PipelinePedidoCard(
                id_pedido=int(pedido.idPedido),
                numero_pedido=_numero_pedido(pedido),
                cliente_nombre=str(cliente.nombreCompleto or "Cliente"),
                telefono=str((cliente.telefonoCompleto or cliente.telefono or "") or ""),
                fecha_entrega=fecha_entrega,
                hora_entrega=_hora_text(fecha_entrega),
                rango_hora=rango_hora_valor,
                direccion=(str(entrega.direccion) if entrega and entrega.direccion else None),
                total=float(pedido.totalNeto or 0),
                estado=stage,
                sucursal=sucursal_map.get(int(pedido.sucursalID), f"Sucursal {int(pedido.sucursalID)}"),
                sucursal_id=(int(pedido.sucursalID) if pedido.sucursalID is not None else None),
                domiciliario=(
                    str(domiciliario.nombre)
                    if domiciliario and domiciliario.nombre
                    else (f"Domiciliario {domiciliario_id_value}" if domiciliario_id_value is not None else None)
                ),
                domiciliario_id=domiciliario_id_value,
                florista=(
                    str(florista.nombre)
                    if florista and florista.nombre
                    else (f"Florista {florista_id_value}" if florista_id_value is not None else None)
                ),
                florista_id=florista_id_value,
                prioridad=prioridad,
                urgente=urgente,
                tiempo_estimado_produccion=(int(produccion.tiempoEstimadoMin) if produccion and produccion.tiempoEstimadoMin is not None else None),
                tiempo_restante_entrega=_minutes_left(fecha_entrega, rango_hora_valor),
                progreso_porcentaje=STAGE_PROGRESS[stage],
                resumen_productos=resumen,
                color_estado=STAGE_COLOR[stage],
                tiene_tarjeta=tiene_tarjeta,
                tipo_entrega=(str(entrega.tipoEntrega).strip() if entrega and entrega.tipoEntrega else None),
                es_domicilio=bool(entrega and str(entrega.tipoEntrega or "").strip().lower() != "recoger"),
                stage=stage,
            )
            board[stage].append(card)

        for stage in board.keys():
            board[stage] = sort_operativo(
                board[stage],
                due_at=lambda item: item.fecha_entrega,
                priority=lambda item: item.prioridad,
            )

        return PipelinePedidosResponse(**board)
    except HTTPException:
        raise
    except Exception:
        pipeline_logger.error("Error construyendo pipeline operativo", exc_info=True)
        raise _err("PIPELINE_INTERNAL_ERROR", "Error interno del servidor", status_code=500)
