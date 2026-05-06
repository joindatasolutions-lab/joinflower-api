from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, cast, func, or_, text
from sqlalchemy.orm import Session, aliased

from app.core.logger import get_logger
from app.core.ordering import sort_operativo
from app.core.security import assert_same_empresa, get_current_auth_context, require_module_access
from app.database import get_db
from app.models.cliente import Cliente
from app.models.domiciliario import Domiciliario
from app.models.entrega import Entrega
from app.models.estadopedido import EstadoPedido
from app.models.florista import Florista
from app.models.pedido import Pedido
from app.models.pedidodetalle import PedidoDetalle
from app.models.producto import Producto
from app.models.produccion import Produccion
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
    if not dt:
        return None
    return dt.strftime("%H:%M")


def _minutes_left(target: datetime | None) -> int | None:
    if not target:
        return None
    now = datetime.now()
    delta = target - now
    return int(delta.total_seconds() // 60)


def _resolve_stage(
    pedido_estado: str | None,
    prod_estado: int | None,
    entrega_estado: int | None,
) -> PipelineStage:
    pedido_key = str(pedido_estado or "").strip().upper()
    if pedido_key == "CANCELADO":
        return "cancelado"

    if entrega_estado in {6}:
        return "cancelado"
    if entrega_estado in {4}:
        return "entregado"
    if entrega_estado in {3}:
        return "en_camino"

    if prod_estado in {5}:
        return "cancelado"
    if prod_estado in {4}:
        return "listo"
    if prod_estado in {2, 3}:
        return "en_produccion"
    if prod_estado in {1}:
        return "pendiente_produccion"

    if pedido_key == "CREADO":
        return "creado"
    if pedido_key == "APROBADO":
        return "aprobado"
    return "aprobado"


@router.get("/pedidos", response_model=PipelinePedidosResponse)
def listar_pipeline_pedidos(
    empresa_id: int = Query(..., alias="empresaID"),
    sucursal_id: int | None = Query(None, alias="sucursalID"),
    fecha: date | None = Query(None),
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
        FloristaLast = aliased(Florista)

        q = (
            db.query(Pedido, Cliente, EstadoPedido, EntregaLast, ProduccionLast, Domiciliario)
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
                (FloristaLast.idFlorista == ProduccionLast.floristaID)
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

        if fecha:
            start = datetime.combine(fecha, datetime.min.time())
            end = datetime.combine(fecha, datetime.max.time())
            q = q.filter(Pedido.fechaPedido.between(start, end))
        elif solo_hoy:
            today = date.today()
            start = datetime.combine(today, datetime.min.time())
            end = datetime.combine(today, datetime.max.time())
            q = q.filter(Pedido.fechaPedido.between(start, end))

        rows = q.order_by(Pedido.fechaPedido.desc(), Pedido.idPedido.desc()).all()
        pedido_ids = [int(row[0].idPedido) for row in rows]

        productos_por_pedido: dict[int, str] = {}
        if pedido_ids:
            det_rows = (
                db.query(
                    PedidoDetalle.pedidoID,
                    func.string_agg(Producto.nombreProducto, ", ").label("resumen"),
                )
                .join(Producto, Producto.idProducto == PedidoDetalle.productoID)
                .filter(PedidoDetalle.pedidoID.in_(pedido_ids))
                .group_by(PedidoDetalle.pedidoID)
                .all()
            )
            productos_por_pedido = {int(pid): str(resumen or "") for pid, resumen in det_rows}

        sucursal_map: dict[int, str] = {}
        if pedido_ids:
            sucursal_ids = sorted({int(row[0].sucursalID) for row in rows if row[0].sucursalID is not None})
            if sucursal_ids:
                rows_s = db.execute(
                    text(
                        """
                        SELECT id_sucursal, nombre_sucursal
                        FROM petalops.sucursal
                        WHERE empresa_id = :empresa_id
                          AND id_sucursal = ANY(:ids)
                        """
                    ),
                    {"empresa_id": int(empresa_id), "ids": sucursal_ids},
                ).all()
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

        for pedido, cliente, estado_pedido, entrega, produccion, domiciliario in rows:
            stage = _resolve_stage(
                (estado_pedido.nombreEstado if estado_pedido else None),
                (int(produccion.estado) if produccion and produccion.estado is not None else None),
                (int(entrega.estadoEntregaID) if entrega and entrega.estadoEntregaID is not None else None),
            )

            if solo_en_produccion and stage != "en_produccion":
                continue

            fecha_entrega = (
                entrega.reprogramadaPara
                if entrega and entrega.reprogramadaPara
                else (entrega.fechaEntregaProgramada if entrega else None)
            )
            if solo_atrasados and (fecha_entrega is None or fecha_entrega >= datetime.now()):
                continue

            prioridad = (str(produccion.prioridad or "MEDIA").upper() if produccion else "MEDIA")
            urgente = prioridad in {"ALTA", "URGENTE", "CRITICA"}
            resumen = productos_por_pedido.get(int(pedido.idPedido), "")
            tiene_tarjeta = bool(entrega and entrega.mensaje and str(entrega.mensaje).strip())

            card = PipelinePedidoCard(
                id_pedido=int(pedido.idPedido),
                numero_pedido=_numero_pedido(pedido),
                cliente_nombre=str(cliente.nombreCompleto or "Cliente"),
                telefono=str((cliente.telefonoCompleto or cliente.telefono or "") or ""),
                fecha_entrega=fecha_entrega,
                hora_entrega=_hora_text(fecha_entrega),
                direccion=(str(entrega.direccion) if entrega and entrega.direccion else None),
                total=float(pedido.totalNeto or 0),
                estado=stage,
                sucursal=sucursal_map.get(int(pedido.sucursalID), f"Sucursal {int(pedido.sucursalID)}"),
                sucursal_id=(int(pedido.sucursalID) if pedido.sucursalID is not None else None),
                domiciliario=(str(domiciliario.nombre) if domiciliario and domiciliario.nombre else None),
                domiciliario_id=(int(entrega.domiciliarioID) if entrega and entrega.domiciliarioID is not None else None),
                florista_id=(int(produccion.floristaID) if produccion and produccion.floristaID is not None else None),
                prioridad=prioridad,
                urgente=urgente,
                tiempo_estimado_produccion=(int(produccion.tiempoEstimadoMin) if produccion and produccion.tiempoEstimadoMin is not None else None),
                tiempo_restante_entrega=_minutes_left(fecha_entrega),
                progreso_porcentaje=STAGE_PROGRESS[stage],
                resumen_productos=resumen,
                imagen_url=(
                    str(entrega.evidenciaFotoUrl or entrega.firmaImagenUrl)
                    if entrega and (entrega.evidenciaFotoUrl or entrega.firmaImagenUrl)
                    else None
                ),
                color_estado=STAGE_COLOR[stage],
                tiene_tarjeta=tiene_tarjeta,
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
