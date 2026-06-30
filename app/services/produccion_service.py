from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import String, func, text
from sqlalchemy.orm import Session

from app.core.timezone import as_colombia_date, colombia_now_naive, colombia_today
from app.models.entrega import Entrega
from app.models.florista import Florista
from app.models.pedidodetalle import PedidoDetalle
from app.models.perfilflorista import PerfilFlorista
from app.models.pedido import Pedido
from app.models.produccion import Produccion
from app.models.produccionhistorial import ProduccionHistorial

ESTADO_PENDIENTE = "Pendiente"
ESTADO_EN_PRODUCCION = "EnProduccion"
ESTADO_PARA_ENTREGA = "ParaEntrega"
ESTADO_CANCELADO = "Cancelado"
ESTADO_PRODUCCION_BLOQUEADO_ID = 5


def _activo_truthy(column):
    return func.lower(func.cast(column, String)).in_(["true", "t", "1"])


def _as_date(value: date | datetime | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    return value


def cancelar_producciones_por_pedido_cancelado(
    db: Session,
    *,
    pedido_id: int,
    empresa_id: int,
    usuario: str = "system",
    motivo: str | None = None,
) -> int:
    producciones = (
        db.query(Produccion)
        .join(
            Pedido,
            (Pedido.idPedido == Produccion.pedidoID)
            & (Pedido.empresaID == Produccion.empresaID),
        )
        .filter(
            Produccion.pedidoID == int(pedido_id),
            Produccion.empresaID == int(empresa_id),
            Pedido.estadoPedidoID == 6,
            Produccion.estado != ESTADO_PRODUCCION_BLOQUEADO_ID,
        )
        .all()
    )
    now = colombia_now_naive()
    note = str(motivo or f"Cancelado automaticamente porque el pedido {int(pedido_id)} quedo en estado 6.").strip()

    for produccion in producciones:
        anterior = int(produccion.floristaID) if produccion.floristaID is not None else None
        produccion.estado = ESTADO_PRODUCCION_BLOQUEADO_ID
        produccion.updatedAt = now
        if note:
            current = str(produccion.observacionesInternas or "").strip()
            produccion.observacionesInternas = f"{current}\n{note}" if current and note not in current else (current or note)
        log_historial(
            db=db,
            produccion=produccion,
            florista_anterior_id=anterior,
            florista_nuevo_id=anterior,
            motivo=note,
            usuario=usuario,
        )

    return len(producciones)


def entrega_fecha_programada(entrega: Entrega | None) -> datetime | None:
    if not entrega:
        return None
    return (
        getattr(entrega, "reprogramadaPara", None)
        or getattr(entrega, "fechaEntregaProgramada", None)
        or getattr(entrega, "fechaEntrega", None)
    )


def _resolve_estado_produccion_ids(db: Session) -> dict[str, int]:
    rows = db.execute(
        text(
            """
            SELECT id_estado_produccion, lower(coalesce(codigo, nombre))
            FROM petalops.estado_produccion
            """
        )
    ).fetchall()

    by_code = {str(code): int(state_id) for state_id, code in rows}
    return {
        "pendiente": by_code.get("pendiente", 1),
        "en_proceso": by_code.get("en_proceso", 3),
        "terminado": by_code.get("terminado", by_code.get("listo", 4)),
        "cancelado": by_code.get("cancelado", 5),
    }


def _resolve_estado_produccion_labels(db: Session) -> dict[int, str]:
    default_ids = _resolve_estado_produccion_ids(db)
    labels: dict[int, str] = {
        int(default_ids["pendiente"]): ESTADO_PENDIENTE,
        int(default_ids["en_proceso"]): ESTADO_EN_PRODUCCION,
        int(default_ids["terminado"]): ESTADO_PARA_ENTREGA,
        int(default_ids["cancelado"]): ESTADO_CANCELADO,
    }
    rows = db.execute(
        text(
            """
            SELECT id_estado_produccion, lower(coalesce(codigo, nombre))
            FROM petalops.estado_produccion
            """
        )
    ).fetchall()

    for state_id, raw_code in rows:
        code = str(raw_code or "").strip().lower()
        if code == "pendiente":
            labels[int(state_id)] = ESTADO_PENDIENTE
        elif code == "en_proceso":
            labels[int(state_id)] = ESTADO_EN_PRODUCCION
        elif code in {"terminado", "listo"}:
            labels[int(state_id)] = ESTADO_PARA_ENTREGA
        elif code == "cancelado":
            labels[int(state_id)] = ESTADO_CANCELADO
    return labels


def estado_produccion_norm(value: str | int | None, db: Session | None = None) -> str:
    if value is None:
        return ESTADO_PENDIENTE

    if isinstance(value, (int, float)) and db is not None:
        labels = _resolve_estado_produccion_labels(db)
        return labels.get(int(value), str(int(value)))

    text_value = str(value or "").strip()
    if text_value.isdigit() and db is not None:
        labels = _resolve_estado_produccion_labels(db)
        return labels.get(int(text_value), text_value)

    text = text_value.upper().replace("_", "")
    if text in {"PENDIENTE"}:
        return ESTADO_PENDIENTE
    if text in {"ENPRODUCCION", "ENPROCESO"}:
        return ESTADO_EN_PRODUCCION
    if text in {"PARAENTREGA", "LISTO", "TERMINADO"}:
        return ESTADO_PARA_ENTREGA
    if text in {"CANCELADO"}:
        return ESTADO_CANCELADO
    return text_value


def estado_produccion_id(db: Session, value: str | int | None) -> int:
    if isinstance(value, (int, float)):
        return int(value)

    normalized = estado_produccion_norm(value)
    ids = _resolve_estado_produccion_ids(db)
    if normalized == ESTADO_PENDIENTE:
        return ids["pendiente"]
    if normalized == ESTADO_EN_PRODUCCION:
        return ids["en_proceso"]
    if normalized == ESTADO_PARA_ENTREGA:
        return ids["terminado"]
    if normalized == ESTADO_CANCELADO:
        return ids["cancelado"]
    return ids["pendiente"]


def transicion_produccion_permitida(db: Session, empresa_id: int, origen: str | int | None, destino: str | int | None) -> bool:
    origen_id = estado_produccion_id(db, origen)
    destino_id = estado_produccion_id(db, destino)

    transitions = db.execute(
        text(
            """
            SELECT estado_origen_id, estado_destino_id
            FROM petalops.transicion_estado_produccion
            WHERE empresa_id = :empresa_id
            """
        ),
        {"empresa_id": int(empresa_id)},
    ).fetchall()

    if transitions:
        return any(int(row[0]) == origen_id and int(row[1]) == destino_id for row in transitions)

    ids = _resolve_estado_produccion_ids(db)
    fallback = {
        ids["pendiente"]: {ids["en_proceso"], ids["cancelado"]},
        ids["en_proceso"]: {ids["terminado"], ids["cancelado"]},
        ids["terminado"]: set(),
        ids["cancelado"]: set(),
    }
    return destino_id in fallback.get(origen_id, set())


def estado_florista_norm(value: str | None) -> str:
    text = str(value or "").strip().upper()
    if text == "ACTIVO":
        return "Activo"
    if text == "INACTIVO":
        return "Inactivo"
    if text == "INCAPACIDAD":
        return "Incapacidad"
    return str(value or "Activo").strip() or "Activo"


def calcular_fecha_programada(fecha_entrega: datetime | None, dias_anticipacion: int) -> date:
    base = as_colombia_date(fecha_entrega) if fecha_entrega else colombia_today()
    return base - timedelta(days=max(dias_anticipacion, 0))


def is_florista_in_incapacity(florista: Florista, fecha_programada: date) -> bool:
    if estado_florista_norm(florista.estado) != "Incapacidad":
        return False

    start = _as_date(florista.fechaInicioIncapacidad)
    end = _as_date(florista.fechaFinIncapacidad)

    if start and end:
        return start <= fecha_programada <= end
    if start and not end:
        return fecha_programada >= start
    if end and not start:
        return fecha_programada <= end
    return True


def count_carga_florista(
    db: Session,
    empresa_id: int,
    sucursal_id: int,
    florista_id: int,
    fecha_programada: date,
    ignore_produccion_id: int | None = None,
) -> int:
    estados = _resolve_estado_produccion_ids(db)
    q = (
        db.query(func.count(Produccion.idProduccion))
        .filter(
            Produccion.empresaID == empresa_id,
            Produccion.sucursalID == sucursal_id,
            Produccion.floristaID == florista_id,
            Produccion.fechaProgramadaProduccion == fecha_programada,
            Produccion.estado != estados["cancelado"],
        )
    )
    if ignore_produccion_id is not None:
        q = q.filter(Produccion.idProduccion != ignore_produccion_id)

    return int(q.scalar() or 0)


def count_simultaneos_en_produccion(
    db: Session,
    empresa_id: int,
    sucursal_id: int,
    florista_id: int,
    ignore_produccion_id: int | None = None,
) -> int:
    estados = _resolve_estado_produccion_ids(db)
    q = (
        db.query(func.count(Produccion.idProduccion))
        .filter(
            Produccion.empresaID == empresa_id,
            Produccion.sucursalID == sucursal_id,
            Produccion.floristaID == florista_id,
            Produccion.estado == estados["en_proceso"],
        )
    )
    if ignore_produccion_id is not None:
        q = q.filter(Produccion.idProduccion != ignore_produccion_id)

    return int(q.scalar() or 0)


def seleccionar_florista_auto(
    db: Session,
    empresa_id: int,
    sucursal_id: int,
    fecha_programada: date,
    ignore_produccion_id: int | None = None,
    excluded_florista_id: int | None = None,
) -> Florista | None:
    floristas = (
        db.query(Florista)
        .join(PerfilFlorista, PerfilFlorista.empleadoID == Florista.idFlorista)
        .filter(
            Florista.empresaID == empresa_id,
            Florista.sucursalID == sucursal_id,
            func.upper(Florista.cargo) == "FLORISTA",
            _activo_truthy(Florista.activo),
        )
        .all()
    )

    ranking: list[tuple[int, int, Florista]] = []
    for florista in floristas:
        fid = int(florista.idFlorista)
        if excluded_florista_id is not None and fid == excluded_florista_id:
            continue
        if estado_florista_norm(florista.estado) != "Activo":
            continue
        if is_florista_in_incapacity(florista, fecha_programada):
            continue

        ocupacion = count_carga_florista(
            db=db,
            empresa_id=empresa_id,
            sucursal_id=sucursal_id,
            florista_id=fid,
            fecha_programada=fecha_programada,
            ignore_produccion_id=ignore_produccion_id,
        )

        ranking.append((ocupacion, fid, florista))

    ranking.sort(key=lambda item: (item[0], item[1]))
    return ranking[0][2] if ranking else None


def calcular_tiempo_estimado_pedido(db: Session, pedido_id: int) -> int:
    rows = db.query(PedidoDetalle.cantidad).filter(PedidoDetalle.pedidoID == pedido_id).all()

    if not rows:
        return 30

    total = 0
    for (cantidad,) in rows:
        qty = max(float(cantidad or 0), 0)
        base = 30
        total += int(round(base * qty))

    return max(total, 1)


def calcular_tiempo_estimado_detalle(detalle: PedidoDetalle) -> int:
    qty = max(float(detalle.cantidad or 0), 0)
    base = 30
    return max(int(round(base * qty)), 1)


def log_historial(
    db: Session,
    produccion: Produccion,
    florista_anterior_id: int | None,
    florista_nuevo_id: int | None,
    motivo: str,
    usuario: str,
):
    db.add(
        ProduccionHistorial(
            empresaID=int(produccion.empresaID),
            sucursalID=int(produccion.sucursalID),
            produccionID=int(produccion.idProduccion),
            floristaAnteriorID=florista_anterior_id,
            floristaNuevoID=florista_nuevo_id,
            fechaCambio=colombia_now_naive(),
            motivo=(motivo or "Sin motivo").strip(),
            usuarioCambio=(usuario or "system").strip() or "system",
        )
    )


def asegurar_produccion_desde_pedido_aprobado(
    db: Session,
    pedido: Pedido,
    dias_anticipacion: int,
    usuario: str = "system",
) -> dict[str, Any]:
    estados = _resolve_estado_produccion_ids(db)
    entrega = db.query(Entrega).filter(Entrega.pedidoID == pedido.idPedido).first()
    fecha_programada = calcular_fecha_programada(
        fecha_entrega=entrega_fecha_programada(entrega),
        dias_anticipacion=dias_anticipacion,
    )
    tiempo_estimado = calcular_tiempo_estimado_pedido(db, int(pedido.idPedido))

    existente = (
        db.query(Produccion)
        .filter(
            Produccion.pedidoID == pedido.idPedido,
            Produccion.estado != estados["cancelado"],
        )
        .first()
    )

    if existente:
        return {
            "created": False,
            "produccionID": int(existente.idProduccion),
            "fechaProgramadaProduccion": fecha_programada,
            "autoAsignado": False,
            "mensaje": "Producción ya existente para el pedido",
        }

    siguiente_orden = int(
        db.query(func.max(Produccion.ordenProduccion))
        .filter(
            Produccion.empresaID == pedido.empresaID,
            Produccion.sucursalID == pedido.sucursalID,
            Produccion.fechaProgramadaProduccion == fecha_programada,
        )
        .scalar()
        or 0
    ) + 1

    auto_asignar_hoy = fecha_programada == colombia_today()
    florista = None
    if auto_asignar_hoy:
        florista = seleccionar_florista_auto(
            db=db,
            empresa_id=int(pedido.empresaID),
            sucursal_id=int(pedido.sucursalID),
            fecha_programada=fecha_programada,
        )

    now = colombia_now_naive()
    produccion = Produccion(
        empresaID=int(pedido.empresaID),
        sucursalID=int(pedido.sucursalID),
        pedidoID=int(pedido.idPedido),
        floristaID=(int(florista.idFlorista) if florista else None),
        fechaProgramadaProduccion=fecha_programada,
        fechaAsignacion=(now if florista else None),
        estado=estados["pendiente"],
        prioridad="MEDIA",
        tiempoEstimadoMin=tiempo_estimado,
        ordenProduccion=siguiente_orden,
        createdAt=now,
        updatedAt=now,
    )
    db.add(produccion)
    db.flush()

    if florista:
        log_historial(
            db=db,
            produccion=produccion,
            florista_anterior_id=None,
            florista_nuevo_id=int(florista.idFlorista),
            motivo="Asignación automática por aprobación del pedido (producción de hoy)",
            usuario=usuario,
        )

    return {
        "created": True,
        "produccionID": int(produccion.idProduccion),
        "fechaProgramadaProduccion": fecha_programada,
        "autoAsignado": bool(florista),
        "floristaID": (int(florista.idFlorista) if florista else None),
        "mensaje": (
            "Producción creada y asignada" if florista else "Producción creada pendiente de asignación"
        ),
    }


def asignar_pendientes_hoy(
    db: Session,
    empresa_id: int,
    sucursal_id: int | None = None,
    usuario: str = "system",
    motivo: str = "Asignación automática al abrir módulo de Producción",
) -> dict[str, int]:
    return asignar_pendientes_por_fecha(
        db=db,
        empresa_id=empresa_id,
        fecha_objetivo=colombia_today(),
        sucursal_id=sucursal_id,
        incluir_vencidas=False,
        usuario=usuario,
        motivo=motivo,
    )


def asignar_pendientes_por_fecha(
    db: Session,
    empresa_id: int,
    fecha_objetivo: date,
    sucursal_id: int | None = None,
    incluir_vencidas: bool = False,
    usuario: str = "system",
    motivo: str = "Asignación manual de pendientes",
) -> dict[str, int]:
    estados = _resolve_estado_produccion_ids(db)
    q = (
        db.query(Produccion)
        .filter(
            Produccion.empresaID == empresa_id,
            Produccion.estado == estados["pendiente"],
            Produccion.floristaID.is_(None),
        )
        .order_by(Produccion.fechaProgramadaProduccion.asc(), Produccion.idProduccion.asc())
    )
    if incluir_vencidas:
        q = q.filter(Produccion.fechaProgramadaProduccion <= fecha_objetivo)
    else:
        q = q.filter(Produccion.fechaProgramadaProduccion == fecha_objetivo)
    if sucursal_id is not None:
        q = q.filter(Produccion.sucursalID == sucursal_id)

    pendientes = q.all()

    evaluadas = len(pendientes)
    asignadas = 0
    sin_disponibilidad = 0

    for prod in pendientes:
        florista = seleccionar_florista_auto(
            db=db,
            empresa_id=int(prod.empresaID),
            sucursal_id=int(prod.sucursalID),
            fecha_programada=prod.fechaProgramadaProduccion,
            ignore_produccion_id=int(prod.idProduccion),
        )
        if not florista:
            sin_disponibilidad += 1
            continue

        now = colombia_now_naive()
        prod.floristaID = int(florista.idFlorista)
        prod.fechaAsignacion = now
        prod.updatedAt = now
        log_historial(
            db=db,
            produccion=prod,
            florista_anterior_id=None,
            florista_nuevo_id=int(florista.idFlorista),
            motivo=motivo,
            usuario=usuario,
        )
        asignadas += 1

    return {
        "evaluadas": evaluadas,
        "asignadas": asignadas,
        "sinDisponibilidad": sin_disponibilidad,
    }

def reasignar_pendientes_por_indisponibilidad(
    db: Session,
    florista: Florista,
    usuario: str,
    motivo: str,
) -> dict[str, int]:
    hoy = colombia_today()
    estados = _resolve_estado_produccion_ids(db)
    pendientes = (
        db.query(Produccion)
        .filter(
            Produccion.empresaID == florista.empresaID,
            Produccion.sucursalID == florista.sucursalID,
            Produccion.floristaID == florista.idFlorista,
            Produccion.fechaProgramadaProduccion >= hoy,
            Produccion.estado == estados["pendiente"],
        )
        .all()
    )

    reasignadas = 0
    sin_reemplazo = 0

    for prod in pendientes:
        if estado_florista_norm(florista.estado) == "Incapacidad" and not is_florista_in_incapacity(
            florista, prod.fechaProgramadaProduccion
        ):
            continue

        nuevo = seleccionar_florista_auto(
            db=db,
            empresa_id=int(prod.empresaID),
            sucursal_id=int(prod.sucursalID),
            fecha_programada=prod.fechaProgramadaProduccion,
            ignore_produccion_id=int(prod.idProduccion),
            excluded_florista_id=int(florista.idFlorista),
        )

        anterior = int(prod.floristaID) if prod.floristaID else None
        prod.floristaID = int(nuevo.idFlorista) if nuevo else None
        now = colombia_now_naive()
        prod.fechaAsignacion = now if nuevo else prod.fechaAsignacion
        prod.updatedAt = now
        log_historial(
            db=db,
            produccion=prod,
            florista_anterior_id=anterior,
            florista_nuevo_id=(int(nuevo.idFlorista) if nuevo else None),
            motivo=motivo,
            usuario=usuario,
        )

        if nuevo:
            reasignadas += 1
        else:
            sin_reemplazo += 1

    return {
        "evaluadas": len(pendientes),
        "reasignadas": reasignadas,
        "sinReemplazo": sin_reemplazo,
    }


def sincronizar_incapacidades_y_reasignar(
    db: Session,
    empresa_id: int,
    sucursal_id: int | None = None,
    usuario: str = "system",
) -> dict[str, int]:
    hoy = colombia_today()

    q_base = db.query(Florista).filter(Florista.empresaID == empresa_id)
    if sucursal_id is not None:
        q_base = q_base.filter(Florista.sucursalID == sucursal_id)

    floristas_incapacidad = (
        q_base
        .join(PerfilFlorista, PerfilFlorista.empleadoID == Florista.idFlorista)
        .filter(
            PerfilFlorista.fechaInicioIncapacidad.is_not(None),
            PerfilFlorista.fechaInicioIncapacidad <= hoy,
            (PerfilFlorista.fechaFinIncapacidad.is_(None) | (PerfilFlorista.fechaFinIncapacidad >= hoy)),
        )
        .all()
    )

    reactivados = 0
    reasignadas = 0
    sin_reemplazo = 0

    for florista in floristas_incapacidad:
        fin = _as_date(florista.fechaFinIncapacidad)
        if fin and fin < hoy:
            perfil = db.query(PerfilFlorista).filter(PerfilFlorista.empleadoID == florista.idFlorista).first()
            if perfil:
                perfil.fechaInicioIncapacidad = None
                perfil.fechaFinIncapacidad = None
            florista.activo = 1
            florista.updatedAt = colombia_now_naive()
            reactivados += 1
            continue

        resumen = reasignar_pendientes_por_indisponibilidad(
            db=db,
            florista=florista,
            usuario=usuario,
            motivo="Reasignación automática por incapacidad activa",
        )
        reasignadas += int(resumen["reasignadas"])
        sin_reemplazo += int(resumen["sinReemplazo"])

    return {
        "floristasIncapacidad": len(floristas_incapacidad),
        "reactivados": reactivados,
        "reasignadas": reasignadas,
        "sinReemplazo": sin_reemplazo,
    }


def asegurar_produccion_desde_pedido_aprobado_por_detalle(
    db: Session,
    pedido: Pedido,
    dias_anticipacion: int,
    usuario: str = "system",
) -> dict[str, Any]:
    estados = _resolve_estado_produccion_ids(db)
    entrega = db.query(Entrega).filter(Entrega.pedidoID == pedido.idPedido).first()
    fecha_programada = calcular_fecha_programada(
        fecha_entrega=entrega_fecha_programada(entrega),
        dias_anticipacion=dias_anticipacion,
    )
    detalles = (
        db.query(PedidoDetalle)
        .filter(
            PedidoDetalle.empresaID == int(pedido.empresaID),
            PedidoDetalle.pedidoID == int(pedido.idPedido),
        )
        .order_by(PedidoDetalle.idPedidoDetalle.asc())
        .all()
    )

    if not detalles:
        return {
            "created": False,
            "createdCount": 0,
            "skippedCount": 0,
            "fechaProgramadaProduccion": fecha_programada,
            "autoAsignados": 0,
            "producciones": [],
            "mensaje": "El pedido no tiene detalles para generar produccion",
        }

    existing_by_detail_id = {
        int(prod.pedidoDetalleID): prod
        for prod in db.query(Produccion)
        .filter(
            Produccion.empresaID == int(pedido.empresaID),
            Produccion.pedidoID == int(pedido.idPedido),
            Produccion.pedidoDetalleID.is_not(None),
            Produccion.estado != estados["cancelado"],
        )
        .all()
        if prod.pedidoDetalleID is not None
    }

    siguiente_orden = int(
        db.query(func.max(Produccion.ordenProduccion))
        .filter(
            Produccion.empresaID == pedido.empresaID,
            Produccion.sucursalID == pedido.sucursalID,
            Produccion.fechaProgramadaProduccion == fecha_programada,
        )
        .scalar()
        or 0
    )

    auto_asignar_hoy = fecha_programada == colombia_today()
    now = colombia_now_naive()
    created_items: list[dict[str, Any]] = []
    skipped_count = 0
    auto_asignados = 0

    for detalle in detalles:
        detalle_id = int(detalle.idPedidoDetalle)
        existente = existing_by_detail_id.get(detalle_id)
        if existente:
            skipped_count += 1
            created_items.append(
                {
                    "produccionID": int(existente.idProduccion),
                    "pedidoDetalleID": detalle_id,
                    "autoAsignado": bool(existente.floristaID),
                    "floristaID": (int(existente.floristaID) if existente.floristaID else None),
                    "created": False,
                }
            )
            continue

        siguiente_orden += 1
        florista = None
        if auto_asignar_hoy:
            florista = seleccionar_florista_auto(
                db=db,
                empresa_id=int(pedido.empresaID),
                sucursal_id=int(pedido.sucursalID),
                fecha_programada=fecha_programada,
            )

        produccion = Produccion(
            empresaID=int(pedido.empresaID),
            sucursalID=int(pedido.sucursalID),
            pedidoID=int(pedido.idPedido),
            pedidoDetalleID=detalle_id,
            floristaID=(int(florista.idFlorista) if florista else None),
            fechaProgramadaProduccion=fecha_programada,
            fechaAsignacion=(now if florista else None),
            estado=estados["pendiente"],
            prioridad="MEDIA",
            tiempoEstimadoMin=calcular_tiempo_estimado_detalle(detalle),
            ordenProduccion=siguiente_orden,
            createdAt=now,
            updatedAt=now,
        )
        db.add(produccion)
        db.flush()

        if florista:
            auto_asignados += 1
            log_historial(
                db=db,
                produccion=produccion,
                florista_anterior_id=None,
                florista_nuevo_id=int(florista.idFlorista),
                motivo="Asignacion automatica por aprobacion del pedido (produccion de hoy)",
                usuario=usuario,
            )

        created_items.append(
            {
                "produccionID": int(produccion.idProduccion),
                "pedidoDetalleID": detalle_id,
                "autoAsignado": bool(florista),
                "floristaID": (int(florista.idFlorista) if florista else None),
                "created": True,
            }
        )

    created_count = sum(1 for item in created_items if item["created"])
    if created_count == 0:
        mensaje = "Produccion ya existente para todos los detalles del pedido"
    elif auto_asignados == created_count:
        mensaje = "Producciones creadas y asignadas"
    elif auto_asignados > 0:
        mensaje = "Producciones creadas; algunas quedaron asignadas automaticamente"
    else:
        mensaje = "Producciones creadas pendientes de asignacion"

    return {
        "created": created_count > 0,
        "createdCount": created_count,
        "skippedCount": skipped_count,
        "fechaProgramadaProduccion": fecha_programada,
        "autoAsignados": auto_asignados,
        "producciones": created_items,
        "mensaje": mensaje,
    }

