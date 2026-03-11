from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException

from app.models.entrega import Entrega
from app.models.pedido import Pedido
from app.models.produccion import Produccion
from app.schemas.domicilios import (
    ESTADO_ASIGNADO,
    ESTADO_CANCELADO,
    ESTADO_EN_RUTA,
    ESTADO_ENTREGADO,
    ESTADO_NO_ENTREGADO,
    ESTADO_PENDIENTE,
)

TRANSICIONES_VALIDAS = {
    ESTADO_PENDIENTE: {ESTADO_ASIGNADO, ESTADO_CANCELADO},
    ESTADO_ASIGNADO: {ESTADO_EN_RUTA, ESTADO_CANCELADO},
    ESTADO_EN_RUTA: {ESTADO_ENTREGADO, ESTADO_NO_ENTREGADO},
    ESTADO_ENTREGADO: set(),
    ESTADO_NO_ENTREGADO: {ESTADO_ASIGNADO, ESTADO_CANCELADO},
    ESTADO_CANCELADO: set(),
}


def estado_norm(value: str | None) -> str:
    text = str(value or "").strip().upper().replace("_", "")
    if text == "PENDIENTE":
        return ESTADO_PENDIENTE
    if text == "ASIGNADO":
        return ESTADO_ASIGNADO
    if text in {"ENRUTA", "ENROUTE"}:
        return ESTADO_EN_RUTA
    if text == "ENTREGADO":
        return ESTADO_ENTREGADO
    if text in {"NOENTREGADO", "NOENTREGA"}:
        return ESTADO_NO_ENTREGADO
    if text == "CANCELADO":
        return ESTADO_CANCELADO
    return str(value or "").strip() or ESTADO_PENDIENTE


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def can_transition(current: str, target: str) -> bool:
    return target in TRANSICIONES_VALIDAS.get(current, set())


def assert_transition_allowed(current: str, target: str):
    if current == target:
        return
    if not can_transition(current, target):
        raise HTTPException(status_code=400, detail=f"Transicion no permitida: {current} -> {target}")


def _to_number(value):
    if value is None:
        return None
    return float(value)


def ensure_entrega_desde_produccion(db, produccion: Produccion, pedido: Pedido | None = None) -> Entrega:
    entrega = (
        db.query(Entrega)
        .filter(Entrega.produccionID == produccion.idProduccion)
        .first()
    )

    if not entrega:
        entrega = (
            db.query(Entrega)
            .filter(Entrega.pedidoID == produccion.pedidoID)
            .order_by(Entrega.idEntrega.desc())
            .first()
        )

    current_time = now_utc()

    if not entrega:
        entrega = Entrega(
            empresaID=int(produccion.empresaID),
            sucursalID=int(produccion.sucursalID),
            pedidoID=int(produccion.pedidoID),
            produccionID=int(produccion.idProduccion),
            estadoEntregaID=1,
            estado=ESTADO_PENDIENTE,
            intentoNumero=1,
            fechaAsignacion=None,
            createdAt=current_time,
            updatedAt=current_time,
        )
        db.add(entrega)
        db.flush()
    else:
        entrega.produccionID = int(produccion.idProduccion)
        entrega.sucursalID = int(produccion.sucursalID)
        entrega.estado = estado_norm(entrega.estado) or ESTADO_PENDIENTE
        entrega.updatedAt = current_time

    if pedido and not entrega.fechaEntregaProgramada:
        entrega.fechaEntregaProgramada = entrega.fechaEntrega or pedido.fechaPedido

    if not entrega.fechaEntregaProgramada and entrega.fechaEntrega:
        entrega.fechaEntregaProgramada = entrega.fechaEntrega

    if not entrega.estado:
        entrega.estado = ESTADO_PENDIENTE

    return entrega


def is_produccion_bloqueada_por_entrega_en_ruta(db, produccion_id: int) -> bool:
    row = (
        db.query(Entrega)
        .filter(Entrega.produccionID == produccion_id)
        .first()
    )
    if not row:
        return False
    return estado_norm(row.estado) == ESTADO_EN_RUTA


def tiempo_restante_horas(entrega: Entrega) -> int | None:
    target = entrega.reprogramadaPara or entrega.fechaEntregaProgramada
    if not target:
        return None

    now = now_utc().replace(tzinfo=None)
    if target.tzinfo is not None:
        target = target.astimezone(timezone.utc).replace(tzinfo=None)
    delta = target - now
    return int(delta.total_seconds() // 3600)


def filtro_rango_fecha(filtro: str, base_date: date) -> tuple[datetime, datetime] | None:
    value = str(filtro or "").strip().lower()
    if value == "hoy":
        start = datetime.combine(base_date, datetime.min.time())
        end = datetime.combine(base_date, datetime.max.time())
        return start, end
    if value == "manana":
        dt = base_date + timedelta(days=1)
        start = datetime.combine(dt, datetime.min.time())
        end = datetime.combine(dt, datetime.max.time())
        return start, end
    return None


def estado_from_filtro(filtro: str) -> str | None:
    value = str(filtro or "").strip().lower()
    if value == "pendientes":
        return ESTADO_PENDIENTE
    if value == "enruta":
        return ESTADO_EN_RUTA
    if value == "noentregado":
        return ESTADO_NO_ENTREGADO
    return None


def payload_lat_lng(entrega: Entrega) -> tuple[float | None, float | None]:
    return _to_number(entrega.latitudEntrega), _to_number(entrega.longitudEntrega)
