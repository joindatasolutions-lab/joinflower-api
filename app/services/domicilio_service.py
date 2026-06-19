from __future__ import annotations

import os
from math import atan2, cos, radians, sin, sqrt

from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.models.entrega import Entrega
from app.models.estadoentrega import EstadoEntrega
from app.models.pedido import Pedido
from app.models.produccion import Produccion
from app.models.transicionestadoentrega import TransicionEstadoEntrega
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

# Fallback IDs when estado_entrega catalog is not seeded yet.
ESTADO_ID_FALLBACK = {
    ESTADO_PENDIENTE: 1,
    ESTADO_ASIGNADO: 2,
    ESTADO_EN_RUTA: 3,
    ESTADO_ENTREGADO: 4,
    ESTADO_NO_ENTREGADO: 5,
    ESTADO_CANCELADO: 6,
}
ESTADO_FROM_ID_FALLBACK = {v: k for k, v in ESTADO_ID_FALLBACK.items()}


def estado_norm(value: str | int | None) -> str:
    if value is None:
        return ESTADO_PENDIENTE

    if isinstance(value, (int, float)):
        return ESTADO_FROM_ID_FALLBACK.get(int(value), ESTADO_PENDIENTE)

    text = str(value).strip()
    if text.isdigit():
        return ESTADO_FROM_ID_FALLBACK.get(int(text), ESTADO_PENDIENTE)

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


def estado_id(value: str | int | None) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    normalized = estado_norm(value)
    return ESTADO_ID_FALLBACK.get(normalized, ESTADO_ID_FALLBACK[ESTADO_PENDIENTE])


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


DEFAULT_DOMICILIO_MAX_TAREAS_ACTIVAS = 20


def domicilio_max_tareas_activas() -> int:
    raw = os.getenv("DOMICILIO_MAX_TAREAS_ACTIVAS")
    if raw is None or str(raw).strip() == "":
        return DEFAULT_DOMICILIO_MAX_TAREAS_ACTIVAS
    try:
        return int(raw)
    except (TypeError, ValueError):
        return DEFAULT_DOMICILIO_MAX_TAREAS_ACTIVAS


def can_transition(current: str, target: str) -> bool:
    return target in TRANSICIONES_VALIDAS.get(current, set())


def assert_transition_allowed(current: str, target: str):
    if current == target:
        return
    if not can_transition(current, target):
        raise HTTPException(status_code=400, detail=f"Transicion no permitida: {current} -> {target}")


def _estado_entrega_table_exists(db: Session) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'petalops'
              AND table_name = 'estado_entrega'
            LIMIT 1
            """
        )
    ).first()
    return bool(row)


def _transicion_estado_entrega_table_exists(db: Session) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'petalops'
              AND table_name = 'transicion_estado_entrega'
            LIMIT 1
            """
        )
    ).first()
    return bool(row)


def resolve_estado_entrega_id(db: Session, value: str | int | None) -> int:
    if isinstance(value, (int, float)):
        return int(value)

    normalized = estado_norm(value)
    fallback_id = ESTADO_ID_FALLBACK.get(normalized, ESTADO_ID_FALLBACK[ESTADO_PENDIENTE])
    if not _estado_entrega_table_exists(db):
        return fallback_id

    row = (
        db.query(EstadoEntrega.idEstadoEntrega)
        .filter(
            func.replace(func.upper(EstadoEntrega.codigo), "_", "")
            == normalized.upper().replace("_", "")
        )
        .first()
    )
    if row:
        return int(row[0])

    return fallback_id


def assert_transition_allowed_for_empresa(
    db: Session,
    empresa_id: int,
    current: str | int | None,
    target: str | int | None,
):
    current_id = resolve_estado_entrega_id(db, current)
    target_id = resolve_estado_entrega_id(db, target)

    if current_id == target_id:
        return

    if _transicion_estado_entrega_table_exists(db):
        row = (
            db.query(TransicionEstadoEntrega.idTrancisionEstadoEntrega)
            .filter(
                TransicionEstadoEntrega.empresaID == int(empresa_id),
                TransicionEstadoEntrega.estadoOrigenID == int(current_id),
                TransicionEstadoEntrega.estadoDestinoID == int(target_id),
            )
            .first()
        )
        if row:
            return
        raise HTTPException(
            status_code=400,
            detail=f"Transicion no permitida: {estado_norm(current)} -> {estado_norm(target)}",
        )

    assert_transition_allowed(estado_norm(current), estado_norm(target))


def _active_entrega_state_ids() -> set[int]:
    return {
        estado_id(ESTADO_ASIGNADO),
        estado_id(ESTADO_EN_RUTA),
    }


def _empleado_has_column(db, column_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'petalops'
              AND table_name = 'empleado'
              AND column_name = :column_name
            LIMIT 1
            """
        ),
        {"column_name": column_name},
    ).first()
    return bool(row)


def _find_domiciliario_id_for_usuario_id(db, empresa_id: int, user_id: int) -> int | None:
    if _empleado_has_column(db, "usuario_id"):
        row = db.execute(
            text(
                "SELECT id_empleado FROM petalops.empleado "
                "WHERE empresa_id = :empresa_id "
                "AND usuario_id = :user_id "
                "AND lower(cargo) = 'domiciliario' "
                "LIMIT 1"
            ),
            {"empresa_id": int(empresa_id), "user_id": int(user_id)},
        ).first()
        if row:
            return int(row[0])

    if _empleado_has_column(db, "user_id"):
        row = db.execute(
            text(
                "SELECT id_empleado FROM petalops.empleado "
                "WHERE empresa_id = :empresa_id "
                "AND user_id = :user_id "
                "AND lower(cargo) = 'domiciliario' "
                "LIMIT 1"
            ),
            {"empresa_id": int(empresa_id), "user_id": int(user_id)},
        ).first()
        if row:
            return int(row[0])

    return None


def _find_domiciliario_id_for_login_or_email(db, empresa_id: int, login: str | None, email: str | None) -> int | None:
    if login and _empleado_has_column(db, "login"):
        row = db.execute(
            text(
                "SELECT id_empleado FROM petalops.empleado "
                "WHERE empresa_id = :empresa_id "
                "AND lower(login) = lower(:login) "
                "AND lower(cargo) = 'domiciliario' "
                "LIMIT 1"
            ),
            {"empresa_id": int(empresa_id), "login": login},
        ).first()
        if row:
            return int(row[0])

    if email and _empleado_has_column(db, "email"):
        row = db.execute(
            text(
                "SELECT id_empleado FROM petalops.empleado "
                "WHERE empresa_id = :empresa_id "
                "AND lower(email) = lower(:email) "
                "AND lower(cargo) = 'domiciliario' "
                "LIMIT 1"
            ),
            {"empresa_id": int(empresa_id), "email": email},
        ).first()
        if row:
            return int(row[0])

    return None


def find_domiciliario_id_for_user(db, auth) -> int | None:
    user_id = getattr(auth, "userID", None)
    empresa_id = getattr(auth, "empresaID", None)
    if user_id is None or empresa_id is None:
        return None

    domic_id = _find_domiciliario_id_for_usuario_id(db, empresa_id, int(user_id))
    if domic_id is not None:
        return domic_id

    return _find_domiciliario_id_for_login_or_email(db, empresa_id, getattr(auth, "login", None), getattr(auth, "email", None))


def count_entregas_activas(db, empresa_id: int, sucursal_id: int | None, domiciliario_id: int, ignore_entrega_id: int | None = None) -> int:
    query = (
        db.query(Entrega)
        .filter(
            Entrega.empresaID == int(empresa_id),
            Entrega.domiciliarioID == int(domiciliario_id),
            Entrega.estadoEntregaID.in_(_active_entrega_state_ids()),
        )
    )
    if sucursal_id is not None:
        query = query.filter(Entrega.sucursalID == int(sucursal_id))
    if ignore_entrega_id is not None:
        query = query.filter(Entrega.idEntrega != int(ignore_entrega_id))
    return int(query.count())


def assert_domiciliario_capacity(db, empresa_id: int, sucursal_id: int | None, domiciliario_id: int, ignore_entrega_id: int | None = None, limit: int | None = None):
    limit = domicilio_max_tareas_activas() if limit is None else int(limit)
    if limit <= 0:
        return
    total = count_entregas_activas(db, empresa_id, sucursal_id, domiciliario_id, ignore_entrega_id=ignore_entrega_id)
    if total >= limit:
        raise HTTPException(
            status_code=400,
            detail=f"El domiciliario tiene {total} entregas activas y el limite permitido es {limit}",
        )


def _to_number(value):
    if value is None:
        return None
    return float(value)


def haversine_distance_km(lat1: float | None, lon1: float | None, lat2: float | None, lon2: float | None) -> float | None:
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return None

    lat1_rad, lon1_rad, lat2_rad, lon2_rad = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    a = sin(dlat / 2) ** 2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(max(0.0, 1.0 - a)))
    return 6371.0 * c


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
        entrega.estadoEntregaID = estado_id(entrega.estadoEntregaID)
        entrega.updatedAt = current_time

    if pedido and not entrega.fechaEntregaProgramada:
        entrega.fechaEntregaProgramada = entrega.fechaEntrega or pedido.fechaPedido

    if not entrega.fechaEntregaProgramada and entrega.fechaEntrega:
        entrega.fechaEntregaProgramada = entrega.fechaEntrega

    if not entrega.estadoEntregaID:
        entrega.estadoEntregaID = ESTADO_ID_FALLBACK[ESTADO_PENDIENTE]

    return entrega


def is_produccion_bloqueada_por_entrega_en_ruta(db, produccion_id: int) -> bool:
    row = (
        db.query(Entrega)
        .filter(Entrega.produccionID == produccion_id)
        .first()
    )
    if not row:
        return False
    return estado_norm(row.estadoEntregaID) == ESTADO_EN_RUTA


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


def payload_destino_lat_lng(entrega: Entrega) -> tuple[float | None, float | None]:
    return _to_number(entrega.latitudDestino), _to_number(entrega.longitudDestino)


def create_retry_entrega(
    db: Session,
    previous: Entrega,
    domiciliario_id: int | None,
    next_state: str,
) -> Entrega:
    current_time = now_utc()
    next_entrega = Entrega(
        empresaID=int(previous.empresaID),
        sucursalID=(int(previous.sucursalID) if previous.sucursalID is not None else None),
        pedidoID=int(previous.pedidoID),
        produccionID=(int(previous.produccionID) if previous.produccionID is not None else None),
        domiciliarioID=(int(domiciliario_id) if domiciliario_id is not None else None),
        empleadoID=(int(previous.empleadoID) if previous.empleadoID is not None else None),
        estadoEntregaID=resolve_estado_entrega_id(db, next_state),
        intentoNumero=max(int(previous.intentoNumero or 1), 1) + 1,
        tipoEntrega=previous.tipoEntrega,
        destinatario=previous.destinatario,
        telefonoDestino=previous.telefonoDestino,
        direccion=previous.direccion,
        barrioID=previous.barrioID,
        barrioNombre=previous.barrioNombre,
        rangoHora=previous.rangoHora,
        mensaje=previous.mensaje,
        observacionGeneral=previous.observacionGeneral,
        fechaAsignacion=(current_time if domiciliario_id is not None else None),
        fechaSalida=None,
        fechaEntregaProgramada=previous.reprogramadaPara or previous.fechaEntregaProgramada or previous.fechaEntrega,
        fechaEntrega=None,
        firma=None,
        latitudDestino=_to_number(previous.latitudDestino),
        longitudDestino=_to_number(previous.longitudDestino),
        latitudEntrega=None,
        longitudEntrega=None,
        firmaNombre=None,
        firmaDocumento=None,
        firmaImagenUrl=None,
        evidenciaFotoUrl=None,
        observaciones=None,
        motivoNoEntregado=None,
        reprogramadaPara=previous.reprogramadaPara,
        createdAt=current_time,
        updatedAt=current_time,
    )
    db.add(next_entrega)
    db.flush()
    return next_entrega
