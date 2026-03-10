from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.entrega import Entrega
from app.models.florista import Florista
from app.models.pedidodetalle import PedidoDetalle
from app.models.pedido import Pedido
from app.models.producto import Producto
from app.models.produccion import Produccion
from app.models.produccionhistorial import ProduccionHistorial

ESTADO_PENDIENTE = "Pendiente"
ESTADO_CANCELADO = "Cancelado"


def estado_florista_norm(value: str | None) -> str:
    text = str(value or "").strip().upper()
    if text == "ACTIVO":
        return "Activo"
    if text == "INACTIVO":
        return "Inactivo"
    if text == "INCAPACIDAD":
        return "Incapacidad"
    return str(value or "Activo").strip() or "Activo"


def estado_produccion_norm(value: str | None) -> str:
    text = str(value or "").strip().upper().replace("_", "")
    if text in {"PENDIENTE"}:
        return "Pendiente"
    if text in {"ENPRODUCCION"}:
        return "EnProduccion"
    if text in {"PARAENTREGA", "LISTO"}:
        return "ParaEntrega"
    if text in {"CANCELADO"}:
        return "Cancelado"
    return str(value or "").strip()


def calcular_fecha_programada(fecha_entrega: datetime | None, dias_anticipacion: int) -> date:
    base = fecha_entrega.date() if fecha_entrega else date.today()
    return base - timedelta(days=max(dias_anticipacion, 0))


def is_florista_in_incapacity(florista: Florista, fecha_programada: date) -> bool:
    if estado_florista_norm(florista.estado) != "Incapacidad":
        return False

    start = florista.fechaInicioIncapacidad
    end = florista.fechaFinIncapacidad

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
    q = (
        db.query(func.count(Produccion.idProduccion))
        .filter(
            Produccion.empresaID == empresa_id,
            Produccion.sucursalID == sucursal_id,
            Produccion.floristaID == florista_id,
            Produccion.fechaProgramadaProduccion == fecha_programada,
            func.upper(Produccion.estado) != "CANCELADO",
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
    q = (
        db.query(func.count(Produccion.idProduccion))
        .filter(
            Produccion.empresaID == empresa_id,
            Produccion.sucursalID == sucursal_id,
            Produccion.floristaID == florista_id,
            func.upper(Produccion.estado) == "ENPRODUCCION",
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
        .filter(
            Florista.empresaID == empresa_id,
            Florista.sucursalID == sucursal_id,
            Florista.activo == True,
        )
        .all()
    )

    ranking: list[tuple[float, int, int, Florista]] = []
    for florista in floristas:
        fid = int(florista.idFlorista)
        if excluded_florista_id is not None and fid == excluded_florista_id:
            continue
        if estado_florista_norm(florista.estado) != "Activo":
            continue
        if is_florista_in_incapacity(florista, fecha_programada):
            continue

        capacidad = max(int(florista.capacidadDiaria or 0), 1)
        ocupacion = count_carga_florista(
            db=db,
            empresa_id=empresa_id,
            sucursal_id=sucursal_id,
            florista_id=fid,
            fecha_programada=fecha_programada,
            ignore_produccion_id=ignore_produccion_id,
        )
        if ocupacion >= capacidad:
            continue

        ratio = ocupacion / capacidad
        ranking.append((ratio, ocupacion, fid, florista))

    ranking.sort(key=lambda item: (item[0], item[1], item[2]))
    return ranking[0][3] if ranking else None


def calcular_tiempo_estimado_pedido(db: Session, pedido_id: int) -> int:
    rows = (
        db.query(PedidoDetalle.cantidad, Producto.tiempoBaseProduccionMin)
        .join(Producto, Producto.idProducto == PedidoDetalle.productoID)
        .filter(PedidoDetalle.pedidoID == pedido_id)
        .all()
    )

    if not rows:
        return 30

    total = 0
    for cantidad, tiempo_base in rows:
        qty = max(float(cantidad or 0), 0)
        base = int(tiempo_base or 30)
        total += int(round(base * qty))

    return max(total, 1)


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
            fechaCambio=datetime.now(timezone.utc),
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
    entrega = db.query(Entrega).filter(Entrega.pedidoID == pedido.idPedido).first()
    fecha_programada = calcular_fecha_programada(
        fecha_entrega=(entrega.fechaEntrega if entrega else None),
        dias_anticipacion=dias_anticipacion,
    )
    tiempo_estimado = calcular_tiempo_estimado_pedido(db, int(pedido.idPedido))

    existente = (
        db.query(Produccion)
        .filter(
            Produccion.pedidoID == pedido.idPedido,
            func.upper(Produccion.estado) != "CANCELADO",
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

    auto_asignar_hoy = fecha_programada == date.today()
    florista = None
    if auto_asignar_hoy:
        florista = seleccionar_florista_auto(
            db=db,
            empresa_id=int(pedido.empresaID),
            sucursal_id=int(pedido.sucursalID),
            fecha_programada=fecha_programada,
        )

    now_utc = datetime.now(timezone.utc)
    produccion = Produccion(
        empresaID=int(pedido.empresaID),
        sucursalID=int(pedido.sucursalID),
        pedidoID=int(pedido.idPedido),
        floristaID=(int(florista.idFlorista) if florista else None),
        fechaProgramadaProduccion=fecha_programada,
        fechaAsignacion=(now_utc if florista else None),
        estado=ESTADO_PENDIENTE,
        prioridad="MEDIA",
        tiempoEstimadoMin=tiempo_estimado,
        ordenProduccion=siguiente_orden,
        createdAt=now_utc,
        updatedAt=now_utc,
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
    hoy = date.today()

    q = (
        db.query(Produccion)
        .filter(
            Produccion.empresaID == empresa_id,
            Produccion.fechaProgramadaProduccion == hoy,
            func.upper(Produccion.estado) == "PENDIENTE",
            Produccion.floristaID.is_(None),
        )
        .order_by(Produccion.idProduccion.asc())
    )
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

        now_utc = datetime.now(timezone.utc)
        prod.floristaID = int(florista.idFlorista)
        prod.fechaAsignacion = now_utc
        prod.updatedAt = now_utc
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
    hoy = date.today()
    pendientes = (
        db.query(Produccion)
        .filter(
            Produccion.empresaID == florista.empresaID,
            Produccion.sucursalID == florista.sucursalID,
            Produccion.floristaID == florista.idFlorista,
            Produccion.fechaProgramadaProduccion >= hoy,
            func.upper(Produccion.estado) == "PENDIENTE",
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
        prod.fechaAsignacion = datetime.now(timezone.utc) if nuevo else prod.fechaAsignacion
        prod.updatedAt = datetime.now(timezone.utc)
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
    hoy = date.today()

    q_base = db.query(Florista).filter(Florista.empresaID == empresa_id)
    if sucursal_id is not None:
        q_base = q_base.filter(Florista.sucursalID == sucursal_id)

    floristas_incapacidad = q_base.filter(func.upper(Florista.estado) == "INCAPACIDAD").all()

    reactivados = 0
    reasignadas = 0
    sin_reemplazo = 0

    for florista in floristas_incapacidad:
        fin = florista.fechaFinIncapacidad
        if fin and fin < hoy:
            florista.estado = "Activo"
            florista.activo = True
            florista.updatedAt = datetime.now(timezone.utc)
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
