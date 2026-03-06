import os
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.cliente import Cliente
from app.models.entrega import Entrega
from app.models.estadopedido import EstadoPedido
from app.models.florista import Florista
from app.models.pedido import Pedido
from app.models.pedidodetalle import PedidoDetalle
from app.models.producto import Producto
from app.models.produccion import Produccion
from app.models.produccionhistorial import ProduccionHistorial
from app.schemas.produccion import (
    FloristaEstadoRequest,
    FloristaItem,
    FloristaListResponse,
    FloristaProductividadItem,
    FloristaProductividadResponse,
    OperativaDiariaItem,
    OperativaDiariaResponse,
    ProduccionAsignarRequest,
    ProduccionEstadoRequest,
    ProduccionGenerarRequest,
    ProduccionItem,
    ProduccionKanbanResponse,
    ProduccionListResponse,
    ProduccionReasignarRequest,
    ProduccionRecalcularPedidoRequest,
    ProduccionResumenResponse,
    ReasignacionHistorialItem,
    ReasignacionHistorialResponse,
)

router = APIRouter(prefix="/produccion", tags=["Produccion"])

ESTADO_PENDIENTE = "Pendiente"
ESTADO_EN_PRODUCCION = "EnProduccion"
ESTADO_PARA_ENTREGA = "ParaEntrega"
ESTADO_CANCELADO = "Cancelado"

ESTADOS_VALIDOS = {
    ESTADO_PENDIENTE,
    ESTADO_EN_PRODUCCION,
    ESTADO_PARA_ENTREGA,
    ESTADO_CANCELADO,
}

TRANSICIONES_VALIDAS = {
    ESTADO_PENDIENTE: {ESTADO_EN_PRODUCCION, ESTADO_CANCELADO},
    ESTADO_EN_PRODUCCION: {ESTADO_PARA_ENTREGA, ESTADO_CANCELADO},
    ESTADO_PARA_ENTREGA: set(),
    ESTADO_CANCELADO: set(),
}


def _estado_produccion_norm(value: str | None) -> str:
    text = str(value or "").strip().upper().replace("_", "")
    if text in {"PENDIENTE"}:
        return ESTADO_PENDIENTE
    if text in {"ENPRODUCCION"}:
        return ESTADO_EN_PRODUCCION
    if text in {"PARAENTREGA", "LISTO"}:
        return ESTADO_PARA_ENTREGA
    if text in {"CANCELADO"}:
        return ESTADO_CANCELADO
    return str(value or "").strip()


def _estado_florista_norm(value: str | None) -> str:
    text = str(value or "").strip().upper()
    if text == "ACTIVO":
        return "Activo"
    if text == "INACTIVO":
        return "Inactivo"
    if text == "INCAPACIDAD":
        return "Incapacidad"
    return str(value or "Activo").strip() or "Activo"


def _numero_pedido_humano(pedido_id: int) -> str:
    return f"PED-{pedido_id:06d}"


def _calcular_fecha_programada(fecha_entrega: datetime | None, dias_anticipacion: int) -> date:
    base = fecha_entrega.date() if fecha_entrega else date.today()
    return base - timedelta(days=max(dias_anticipacion, 0))


def _is_florista_in_incapacity(florista: Florista, fecha_programada: date) -> bool:
    if _estado_florista_norm(florista.estado) != "Incapacidad":
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


def _count_carga_florista(db: Session, empresa_id: int, sucursal_id: int, florista_id: int, fecha_programada: date, ignore_produccion_id: int | None = None) -> int:
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


def _count_simultaneos_en_produccion(db: Session, empresa_id: int, sucursal_id: int, florista_id: int, ignore_produccion_id: int | None = None) -> int:
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


def _validate_florista_disponibilidad(db: Session, florista: Florista, fecha_programada: date, empresa_id: int, sucursal_id: int, ignore_produccion_id: int | None = None):
    if _estado_florista_norm(florista.estado) != "Activo" or bool(florista.activo) is False:
        raise HTTPException(status_code=400, detail="El florista no está Activo")

    if _is_florista_in_incapacity(florista, fecha_programada):
        raise HTTPException(status_code=400, detail="El florista está en incapacidad para la fecha programada")

    capacidad = max(int(florista.capacidadDiaria or 0), 1)
    carga = _count_carga_florista(
        db=db,
        empresa_id=empresa_id,
        sucursal_id=sucursal_id,
        florista_id=int(florista.idFlorista),
        fecha_programada=fecha_programada,
        ignore_produccion_id=ignore_produccion_id,
    )
    if carga >= capacidad:
        raise HTTPException(status_code=400, detail="El florista alcanzó su capacidad diaria")


def _seleccionar_florista_auto(db: Session, empresa_id: int, sucursal_id: int, fecha_programada: date, ignore_produccion_id: int | None = None) -> Florista | None:
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
        if _estado_florista_norm(florista.estado) != "Activo":
            continue
        if _is_florista_in_incapacity(florista, fecha_programada):
            continue

        capacidad = max(int(florista.capacidadDiaria or 0), 1)
        ocupacion = _count_carga_florista(
            db,
            empresa_id=empresa_id,
            sucursal_id=sucursal_id,
            florista_id=int(florista.idFlorista),
            fecha_programada=fecha_programada,
            ignore_produccion_id=ignore_produccion_id,
        )
        if ocupacion >= capacidad:
            continue

        ratio = ocupacion / capacidad
        ranking.append((ratio, ocupacion, int(florista.idFlorista), florista))

    ranking.sort(key=lambda item: (item[0], item[1], item[2]))
    return ranking[0][3] if ranking else None


def _calcular_tiempo_estimado_pedido(db: Session, pedido_id: int) -> int:
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


def _log_historial(
    db: Session,
    produccion: Produccion,
    florista_anterior_id: int | None,
    florista_nuevo_id: int | None,
    motivo: str,
    usuario: str,
):
    item = ProduccionHistorial(
        empresaID=int(produccion.empresaID),
        sucursalID=int(produccion.sucursalID),
        produccionID=int(produccion.idProduccion),
        floristaAnteriorID=florista_anterior_id,
        floristaNuevoID=florista_nuevo_id,
        fechaCambio=datetime.now(timezone.utc),
        motivo=(motivo or "Sin motivo").strip(),
        usuarioCambio=(usuario or "system").strip() or "system",
    )
    db.add(item)


def _build_producto_map(db: Session, produccion_ids: list[int]) -> dict[int, str]:
    if not produccion_ids:
        return {}

    rows = (
        db.query(Produccion.idProduccion, Producto.nombreProducto)
        .join(PedidoDetalle, PedidoDetalle.pedidoID == Produccion.pedidoID)
        .join(Producto, Producto.idProducto == PedidoDetalle.productoID)
        .filter(Produccion.idProduccion.in_(produccion_ids))
        .all()
    )

    out: dict[int, str] = {}
    for produccion_id, nombre_producto in rows:
        key = int(produccion_id)
        if key not in out:
            out[key] = str(nombre_producto or "Producto")
    return out


def _build_items(
    db: Session,
    empresa_id: int,
    sucursal_id: int | None,
    fecha_programada: date | None,
    estado: str | None,
    incluir_cancelado: bool,
) -> list[ProduccionItem]:
    q = (
        db.query(Produccion, Pedido, Cliente, Entrega, Florista)
        .join(Pedido, Pedido.idPedido == Produccion.pedidoID)
        .join(Cliente, Cliente.idCliente == Pedido.clienteID)
        .outerjoin(Entrega, Entrega.pedidoID == Pedido.idPedido)
        .outerjoin(Florista, Florista.idFlorista == Produccion.floristaID)
        .filter(Produccion.empresaID == empresa_id)
    )

    if sucursal_id is not None:
        q = q.filter(Produccion.sucursalID == sucursal_id)
    if fecha_programada is not None:
        q = q.filter(Produccion.fechaProgramadaProduccion == fecha_programada)

    if estado:
        q = q.filter(func.upper(Produccion.estado) == _estado_produccion_norm(estado).upper())
    elif not incluir_cancelado:
        q = q.filter(func.upper(Produccion.estado) != "CANCELADO")

    rows = q.order_by(Produccion.fechaProgramadaProduccion.asc(), Produccion.ordenProduccion.asc(), Produccion.idProduccion.asc()).all()
    ids = [int(p.idProduccion) for p, _, _, _, _ in rows]
    producto_map = _build_producto_map(db, ids)

    now_utc = datetime.now(timezone.utc)
    items: list[ProduccionItem] = []

    for produccion, pedido, cliente, entrega, florista in rows:
        fecha_entrega = entrega.fechaEntrega if entrega else None
        tiempo_restante_horas = None
        if fecha_entrega:
            delta = fecha_entrega.replace(tzinfo=timezone.utc) - now_utc
            tiempo_restante_horas = int(delta.total_seconds() // 3600)

        items.append(
            ProduccionItem(
                idProduccion=int(produccion.idProduccion),
                pedidoID=int(pedido.idPedido),
                numeroPedido=_numero_pedido_humano(int(pedido.idPedido)),
                producto=producto_map.get(int(produccion.idProduccion), "Producto"),
                cliente=str(cliente.nombreCompleto or "Cliente"),
                fechaEntrega=(entrega.fechaEntrega if entrega else None),
                horaEntrega=(entrega.rangoHora if entrega else None),
                floristaAsignado=(florista.nombre if florista else None),
                estado=_estado_produccion_norm(produccion.estado),
                fechaAsignacion=produccion.fechaAsignacion,
                tiempoRestanteHoras=tiempo_restante_horas,
                tiempoEstimadoMin=(int(produccion.tiempoEstimadoMin) if produccion.tiempoEstimadoMin is not None else None),
                tiempoRealMin=(int(produccion.tiempoRealMin) if produccion.tiempoRealMin is not None else None),
                prioridad=str(produccion.prioridad or "MEDIA"),
                fechaProgramadaProduccion=produccion.fechaProgramadaProduccion,
            )
        )

    return items


def _dias_anticipacion_default() -> int:
    return max(int(os.getenv("PRODUCCION_DIAS_ANTICIPACION", "0")), 0)


@router.post("/generar-desde-pedidos")
def generar_desde_pedidos(payload: ProduccionGenerarRequest, db: Session = Depends(get_db)):
    dias_anticipacion = payload.diasAnticipacion if payload.diasAnticipacion is not None else _dias_anticipacion_default()

    estado_ids = [
        int(row[0])
        for row in (
            db.query(EstadoPedido.idEstadoPedido)
            .filter(func.upper(EstadoPedido.nombreEstado).in_(["APROBADO", "PAGADO"]))
            .all()
        )
    ]

    if not estado_ids:
        return {"created": 0, "message": "No hay estados APROBADO/PAGADO configurados"}

    q = (
        db.query(Pedido, Entrega)
        .outerjoin(Entrega, Entrega.pedidoID == Pedido.idPedido)
        .filter(Pedido.empresaID == payload.empresaID, Pedido.estadoPedidoID.in_(estado_ids))
    )
    if payload.sucursalID is not None:
        q = q.filter(Pedido.sucursalID == payload.sucursalID)

    created = 0
    for pedido, entrega in q.all():
        existe = (
            db.query(Produccion.idProduccion)
            .filter(
                Produccion.pedidoID == pedido.idPedido,
                func.upper(Produccion.estado) != "CANCELADO",
            )
            .first()
        )
        if existe:
            continue

        fecha_programada = _calcular_fecha_programada(entrega.fechaEntrega if entrega else None, dias_anticipacion)
        tiempo_estimado = _calcular_tiempo_estimado_pedido(db, int(pedido.idPedido))

        florista = None
        if payload.autoAsignar:
            florista = _seleccionar_florista_auto(
                db=db,
                empresa_id=int(pedido.empresaID),
                sucursal_id=int(pedido.sucursalID),
                fecha_programada=fecha_programada,
            )

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

        now_utc = datetime.now(timezone.utc)
        db.add(
            Produccion(
                empresaID=int(pedido.empresaID),
                sucursalID=int(pedido.sucursalID),
                pedidoID=int(pedido.idPedido),
                floristaID=int(florista.idFlorista) if florista else None,
                fechaProgramadaProduccion=fecha_programada,
                fechaAsignacion=now_utc if florista else None,
                estado=ESTADO_PENDIENTE,
                prioridad="MEDIA",
                tiempoEstimadoMin=tiempo_estimado,
                ordenProduccion=siguiente_orden,
                createdAt=now_utc,
                updatedAt=now_utc,
            )
        )
        created += 1

    db.commit()
    return {"created": created}


@router.get("/floristas", response_model=FloristaListResponse)
def listar_floristas(
    empresa_id: int = Query(..., alias="empresaID"),
    sucursal_id: int | None = Query(None, alias="sucursalID"),
    solo_activos: bool = Query(True, alias="soloActivos"),
    db: Session = Depends(get_db),
):
    q = db.query(Florista).filter(Florista.empresaID == empresa_id)
    if sucursal_id is not None:
        q = q.filter(Florista.sucursalID == sucursal_id)
    if solo_activos:
        q = q.filter(Florista.activo == True)

    rows = q.order_by(Florista.nombre.asc()).all()

    return FloristaListResponse(
        items=[
            FloristaItem(
                idFlorista=int(row.idFlorista),
                nombre=str(row.nombre),
                capacidadDiaria=int(row.capacidadDiaria or 0),
                trabajosSimultaneosPermitidos=int(row.trabajosSimultaneosPermitidos or 1),
                estado=_estado_florista_norm(row.estado),
                fechaInicioIncapacidad=row.fechaInicioIncapacidad,
                fechaFinIncapacidad=row.fechaFinIncapacidad,
                activo=bool(row.activo),
                especialidades=row.especialidades,
            )
            for row in rows
        ]
    )


@router.put("/floristas/{florista_id}/estado")
def actualizar_estado_florista(florista_id: int, payload: FloristaEstadoRequest, db: Session = Depends(get_db)):
    florista = db.query(Florista).filter(Florista.idFlorista == florista_id).first()
    if not florista:
        raise HTTPException(status_code=404, detail="Florista no encontrado")

    nuevo_estado = _estado_florista_norm(payload.estado)
    if nuevo_estado not in {"Activo", "Inactivo", "Incapacidad"}:
        raise HTTPException(status_code=400, detail="Estado de florista inválido")

    florista.estado = nuevo_estado
    florista.activo = nuevo_estado == "Activo"
    florista.fechaInicioIncapacidad = payload.fechaInicioIncapacidad
    florista.fechaFinIncapacidad = payload.fechaFinIncapacidad
    florista.updatedAt = datetime.now(timezone.utc)

    reasignadas = 0
    requiere_manual = 0

    if nuevo_estado == "Incapacidad":
        hoy = date.today()
        pendientes_futuras = (
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

        for prod in pendientes_futuras:
            nuevo = _seleccionar_florista_auto(
                db,
                empresa_id=int(prod.empresaID),
                sucursal_id=int(prod.sucursalID),
                fecha_programada=prod.fechaProgramadaProduccion,
                ignore_produccion_id=int(prod.idProduccion),
            )
            anterior = int(prod.floristaID) if prod.floristaID else None
            prod.floristaID = int(nuevo.idFlorista) if nuevo else None
            prod.fechaAsignacion = datetime.now(timezone.utc) if nuevo else prod.fechaAsignacion
            prod.updatedAt = datetime.now(timezone.utc)
            _log_historial(
                db,
                produccion=prod,
                florista_anterior_id=anterior,
                florista_nuevo_id=(int(nuevo.idFlorista) if nuevo else None),
                motivo=(payload.motivo or "Reasignación automática por incapacidad del florista"),
                usuario=payload.usuarioCambio,
            )
            reasignadas += 1

        requiere_manual = int(
            db.query(func.count(Produccion.idProduccion))
            .filter(
                Produccion.empresaID == florista.empresaID,
                Produccion.sucursalID == florista.sucursalID,
                Produccion.floristaID == florista.idFlorista,
                func.upper(Produccion.estado) == "ENPRODUCCION",
            )
            .scalar()
            or 0
        )

    db.commit()

    return {
        "status": "ok",
        "floristaID": florista_id,
        "estado": nuevo_estado,
        "reasignadasAutomaticamente": reasignadas,
        "enProduccionRequierenAccionManual": requiere_manual,
    }


@router.get("", response_model=ProduccionListResponse)
def listar_produccion(
    empresa_id: int = Query(..., alias="empresaID"),
    sucursal_id: int | None = Query(None, alias="sucursalID"),
    fecha: date | None = Query(None),
    estado: str | None = Query(None),
    incluir_cancelado: bool = Query(False, alias="incluirCancelado"),
    db: Session = Depends(get_db),
):
    items = _build_items(
        db=db,
        empresa_id=empresa_id,
        sucursal_id=sucursal_id,
        fecha_programada=(fecha or date.today()),
        estado=estado,
        incluir_cancelado=incluir_cancelado,
    )
    return ProduccionListResponse(items=items, total=len(items))


@router.get("/resumen", response_model=ProduccionResumenResponse)
def resumen_produccion(
    empresa_id: int = Query(..., alias="empresaID"),
    sucursal_id: int | None = Query(None, alias="sucursalID"),
    fecha: date | None = Query(None),
    db: Session = Depends(get_db),
):
    items = _build_items(
        db=db,
        empresa_id=empresa_id,
        sucursal_id=sucursal_id,
        fecha_programada=(fecha or date.today()),
        estado=None,
        incluir_cancelado=True,
    )

    counters = {
        ESTADO_PENDIENTE: 0,
        ESTADO_EN_PRODUCCION: 0,
        ESTADO_PARA_ENTREGA: 0,
        ESTADO_CANCELADO: 0,
    }
    for item in items:
        key = _estado_produccion_norm(item.estado)
        counters[key] = counters.get(key, 0) + 1

    return ProduccionResumenResponse(
        pendiente=counters.get(ESTADO_PENDIENTE, 0),
        enProduccion=counters.get(ESTADO_EN_PRODUCCION, 0),
        paraEntrega=counters.get(ESTADO_PARA_ENTREGA, 0),
        cancelado=counters.get(ESTADO_CANCELADO, 0),
    )


@router.get("/kanban", response_model=ProduccionKanbanResponse)
def kanban_produccion(
    empresa_id: int = Query(..., alias="empresaID"),
    sucursal_id: int | None = Query(None, alias="sucursalID"),
    fecha: date | None = Query(None),
    db: Session = Depends(get_db),
):
    items = _build_items(
        db=db,
        empresa_id=empresa_id,
        sucursal_id=sucursal_id,
        fecha_programada=(fecha or date.today()),
        estado=None,
        incluir_cancelado=True,
    )
    grouped = {
        ESTADO_PENDIENTE: [],
        ESTADO_EN_PRODUCCION: [],
        ESTADO_PARA_ENTREGA: [],
        ESTADO_CANCELADO: [],
    }
    for item in items:
        grouped[_estado_produccion_norm(item.estado)].append(item)

    return ProduccionKanbanResponse(
        pendiente=grouped[ESTADO_PENDIENTE],
        enProduccion=grouped[ESTADO_EN_PRODUCCION],
        paraEntrega=grouped[ESTADO_PARA_ENTREGA],
        cancelado=grouped[ESTADO_CANCELADO],
    )


@router.put("/{produccion_id}/asignar")
def asignar_produccion(produccion_id: int, payload: ProduccionAsignarRequest, db: Session = Depends(get_db)):
    produccion = db.query(Produccion).filter(Produccion.idProduccion == produccion_id).first()
    if not produccion:
        raise HTTPException(status_code=404, detail="Registro de producción no encontrado")

    fecha_programada = payload.fechaProgramadaProduccion or produccion.fechaProgramadaProduccion
    if not fecha_programada:
        raise HTTPException(status_code=400, detail="fechaProgramadaProduccion es obligatoria")

    estado_actual = _estado_produccion_norm(produccion.estado)
    if estado_actual == ESTADO_EN_PRODUCCION and not (payload.motivo and payload.usuarioCambio):
        raise HTTPException(status_code=400, detail="Para reasignar en EnProduccion debes indicar motivo y usuarioCambio")

    if payload.floristaID is not None:
        florista = (
            db.query(Florista)
            .filter(
                Florista.idFlorista == payload.floristaID,
                Florista.empresaID == produccion.empresaID,
                Florista.sucursalID == produccion.sucursalID,
            )
            .first()
        )
        if not florista:
            raise HTTPException(status_code=404, detail="Florista no encontrado")
    else:
        florista = _seleccionar_florista_auto(
            db,
            empresa_id=int(produccion.empresaID),
            sucursal_id=int(produccion.sucursalID),
            fecha_programada=fecha_programada,
            ignore_produccion_id=int(produccion.idProduccion),
        )
        if not florista:
            raise HTTPException(status_code=400, detail="No hay floristas disponibles para asignación automática")

    _validate_florista_disponibilidad(
        db=db,
        florista=florista,
        fecha_programada=fecha_programada,
        empresa_id=int(produccion.empresaID),
        sucursal_id=int(produccion.sucursalID),
        ignore_produccion_id=int(produccion.idProduccion),
    )

    anterior = int(produccion.floristaID) if produccion.floristaID else None
    now_utc = datetime.now(timezone.utc)

    produccion.floristaID = int(florista.idFlorista)
    produccion.fechaProgramadaProduccion = fecha_programada
    produccion.fechaAsignacion = now_utc
    produccion.updatedAt = now_utc

    if payload.prioridad:
        produccion.prioridad = str(payload.prioridad).upper().strip()
    if payload.observacionesInternas:
        produccion.observacionesInternas = payload.observacionesInternas.strip()

    if anterior != int(florista.idFlorista):
        _log_historial(
            db,
            produccion=produccion,
            florista_anterior_id=anterior,
            florista_nuevo_id=int(florista.idFlorista),
            motivo=(payload.motivo or "Reasignación"),
            usuario=(payload.usuarioCambio or "system"),
        )

    db.commit()

    return {
        "status": "ok",
        "idProduccion": produccion_id,
        "floristaID": int(florista.idFlorista),
        "florista": florista.nombre,
        "fechaProgramadaProduccion": str(produccion.fechaProgramadaProduccion),
    }


@router.put("/{produccion_id}/reasignar")
def reasignar_produccion(produccion_id: int, payload: ProduccionReasignarRequest, db: Session = Depends(get_db)):
    if not payload.motivo.strip():
        raise HTTPException(status_code=400, detail="motivo es obligatorio")
    if not payload.usuarioCambio.strip():
        raise HTTPException(status_code=400, detail="usuarioCambio es obligatorio")

    wrapper = ProduccionAsignarRequest(
        floristaID=payload.floristaNuevoID,
        fechaProgramadaProduccion=payload.fechaProgramadaProduccion,
        motivo=payload.motivo,
        usuarioCambio=payload.usuarioCambio,
    )
    return asignar_produccion(produccion_id, wrapper, db)


@router.put("/{produccion_id}/estado")
def cambiar_estado_produccion(produccion_id: int, payload: ProduccionEstadoRequest, db: Session = Depends(get_db)):
    produccion = db.query(Produccion).filter(Produccion.idProduccion == produccion_id).first()
    if not produccion:
        raise HTTPException(status_code=404, detail="Registro de producción no encontrado")

    estado_actual = _estado_produccion_norm(produccion.estado)
    nuevo_estado = _estado_produccion_norm(payload.nuevoEstado)

    if nuevo_estado not in ESTADOS_VALIDOS:
        raise HTTPException(status_code=400, detail=f"Estado inválido. Usa: {', '.join(sorted(ESTADOS_VALIDOS))}")

    if nuevo_estado == estado_actual:
        return {"status": "ok", "idProduccion": produccion_id, "estado": estado_actual}

    if nuevo_estado not in TRANSICIONES_VALIDAS.get(estado_actual, set()):
        raise HTTPException(status_code=400, detail=f"Transición no permitida: {estado_actual} -> {nuevo_estado}")

    if nuevo_estado == ESTADO_EN_PRODUCCION:
        if not produccion.floristaID:
            raise HTTPException(status_code=400, detail="No puedes iniciar producción sin florista asignado")

        florista = db.query(Florista).filter(Florista.idFlorista == produccion.floristaID).first()
        if not florista:
            raise HTTPException(status_code=400, detail="Florista asignado no existe")

        _validate_florista_disponibilidad(
            db=db,
            florista=florista,
            fecha_programada=produccion.fechaProgramadaProduccion,
            empresa_id=int(produccion.empresaID),
            sucursal_id=int(produccion.sucursalID),
            ignore_produccion_id=int(produccion.idProduccion),
        )

        simultaneos = _count_simultaneos_en_produccion(
            db,
            empresa_id=int(produccion.empresaID),
            sucursal_id=int(produccion.sucursalID),
            florista_id=int(produccion.floristaID),
            ignore_produccion_id=int(produccion.idProduccion),
        )
        max_simultaneos = max(int(florista.trabajosSimultaneosPermitidos or 1), 1)
        if simultaneos >= max_simultaneos:
            raise HTTPException(status_code=400, detail="El florista alcanzó sus trabajos simultáneos permitidos")

    now_utc = datetime.now(timezone.utc)
    produccion.estado = nuevo_estado

    if nuevo_estado == ESTADO_EN_PRODUCCION and not produccion.fechaInicio:
        produccion.fechaInicio = now_utc
    if nuevo_estado == ESTADO_PARA_ENTREGA:
        if not produccion.fechaInicio:
            produccion.fechaInicio = now_utc
        produccion.fechaFinalizacion = now_utc
        delta_min = int((produccion.fechaFinalizacion - produccion.fechaInicio).total_seconds() // 60)
        produccion.tiempoRealMin = max(delta_min, 0)

    if payload.observacionesInternas:
        produccion.observacionesInternas = payload.observacionesInternas.strip()

    produccion.updatedAt = now_utc
    db.commit()

    return {
        "status": "ok",
        "idProduccion": produccion_id,
        "estado": nuevo_estado,
        "fechaInicio": produccion.fechaInicio,
        "fechaFinalizacion": produccion.fechaFinalizacion,
        "tiempoRealMin": int(produccion.tiempoRealMin or 0) if produccion.tiempoRealMin is not None else None,
    }


@router.post("/pedido/{pedido_id}/recalcular")
def recalcular_produccion_por_pedido(pedido_id: int, payload: ProduccionRecalcularPedidoRequest, db: Session = Depends(get_db)):
    pedido = db.query(Pedido).filter(Pedido.idPedido == pedido_id).first()
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")

    produccion = (
        db.query(Produccion)
        .filter(Produccion.pedidoID == pedido_id)
        .order_by(Produccion.idProduccion.desc())
        .first()
    )
    if not produccion:
        raise HTTPException(status_code=404, detail="No existe producción asociada al pedido")

    entrega = db.query(Entrega).filter(Entrega.pedidoID == pedido_id).first()
    tiempo_estimado = _calcular_tiempo_estimado_pedido(db, pedido_id)
    fecha_programada = _calcular_fecha_programada(entrega.fechaEntrega if entrega else None, _dias_anticipacion_default())
    estado_actual = _estado_produccion_norm(produccion.estado)

    now_utc = datetime.now(timezone.utc)

    if estado_actual == ESTADO_PENDIENTE:
        produccion.tiempoEstimadoMin = tiempo_estimado
        produccion.fechaProgramadaProduccion = fecha_programada

        if produccion.floristaID:
            florista = db.query(Florista).filter(Florista.idFlorista == produccion.floristaID).first()
            if not florista:
                produccion.floristaID = None
            else:
                try:
                    _validate_florista_disponibilidad(
                        db=db,
                        florista=florista,
                        fecha_programada=fecha_programada,
                        empresa_id=int(produccion.empresaID),
                        sucursal_id=int(produccion.sucursalID),
                        ignore_produccion_id=int(produccion.idProduccion),
                    )
                except HTTPException:
                    nuevo = _seleccionar_florista_auto(
                        db,
                        empresa_id=int(produccion.empresaID),
                        sucursal_id=int(produccion.sucursalID),
                        fecha_programada=fecha_programada,
                        ignore_produccion_id=int(produccion.idProduccion),
                    )
                    anterior = int(produccion.floristaID)
                    produccion.floristaID = int(nuevo.idFlorista) if nuevo else None
                    if anterior != produccion.floristaID:
                        _log_historial(
                            db,
                            produccion,
                            florista_anterior_id=anterior,
                            florista_nuevo_id=produccion.floristaID,
                            motivo=(payload.motivo or "Reasignación por recálculo de pedido"),
                            usuario=payload.usuarioCambio,
                        )

        pedido.version = int(pedido.version or 1) + 1
        produccion.updatedAt = now_utc
        db.commit()
        return {"status": "ok", "modo": "recalculado_pendiente", "versionPedido": int(pedido.version)}

    if estado_actual == ESTADO_EN_PRODUCCION:
        if not payload.productoEstructuralCambiado and not payload.forceCancelarYCrearNueva:
            raise HTTPException(status_code=400, detail="En EnProduccion no se permite cambio estructural sin cancelar y recrear")

        produccion.estado = ESTADO_CANCELADO
        produccion.observacionesInternas = (produccion.observacionesInternas or "") + f"\nCancelado por cambio estructural del pedido v{int(pedido.version or 1)+1}."
        produccion.updatedAt = now_utc

        pedido.version = int(pedido.version or 1) + 1

        nueva = Produccion(
            empresaID=int(pedido.empresaID),
            sucursalID=int(pedido.sucursalID),
            pedidoID=int(pedido.idPedido),
            floristaID=None,
            fechaProgramadaProduccion=fecha_programada,
            fechaAsignacion=None,
            fechaInicio=None,
            fechaFinalizacion=None,
            tiempoEstimadoMin=tiempo_estimado,
            tiempoRealMin=None,
            estado=ESTADO_PENDIENTE,
            prioridad=produccion.prioridad or "MEDIA",
            observacionesInternas=f"Nueva producción por cambio estructural pedido v{pedido.version}",
            ordenProduccion=produccion.ordenProduccion,
            createdAt=now_utc,
            updatedAt=now_utc,
        )
        db.add(nueva)

        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=400, detail="No fue posible crear nueva producción (revisa índice único por pedido en BD)")

        return {"status": "ok", "modo": "cancelada_y_recreada", "versionPedido": int(pedido.version), "nuevaProduccionID": int(nueva.idProduccion)}

    raise HTTPException(status_code=400, detail="Solo se puede recalcular en Pendiente o EnProduccion")


@router.get("/historial/reasignaciones", response_model=ReasignacionHistorialResponse)
def historial_reasignaciones(
    empresa_id: int = Query(..., alias="empresaID"),
    sucursal_id: int | None = Query(None, alias="sucursalID"),
    fecha_desde: date = Query(..., alias="fechaDesde"),
    fecha_hasta: date = Query(..., alias="fechaHasta"),
    db: Session = Depends(get_db),
):
    q = db.query(ProduccionHistorial).filter(
        ProduccionHistorial.empresaID == empresa_id,
        ProduccionHistorial.fechaCambio >= datetime.combine(fecha_desde, datetime.min.time()),
        ProduccionHistorial.fechaCambio <= datetime.combine(fecha_hasta, datetime.max.time()),
    )
    if sucursal_id is not None:
        q = q.filter(ProduccionHistorial.sucursalID == sucursal_id)

    rows = q.order_by(ProduccionHistorial.fechaCambio.desc()).all()
    items = [
        ReasignacionHistorialItem(
            produccionID=int(row.produccionID),
            floristaAnteriorID=(int(row.floristaAnteriorID) if row.floristaAnteriorID else None),
            floristaNuevoID=(int(row.floristaNuevoID) if row.floristaNuevoID else None),
            fechaCambio=row.fechaCambio,
            motivo=row.motivo,
            usuarioCambio=row.usuarioCambio,
        )
        for row in rows
    ]

    return ReasignacionHistorialResponse(items=items, total=len(items))


@router.get("/metricas/productividad", response_model=FloristaProductividadResponse)
def metricas_productividad(
    empresa_id: int = Query(..., alias="empresaID"),
    sucursal_id: int | None = Query(None, alias="sucursalID"),
    fecha_desde: date = Query(..., alias="fechaDesde"),
    fecha_hasta: date = Query(..., alias="fechaHasta"),
    db: Session = Depends(get_db),
):
    q = db.query(Produccion).filter(
        Produccion.empresaID == empresa_id,
        Produccion.fechaProgramadaProduccion >= fecha_desde,
        Produccion.fechaProgramadaProduccion <= fecha_hasta,
    )
    if sucursal_id is not None:
        q = q.filter(Produccion.sucursalID == sucursal_id)

    producciones = q.all()

    florista_ids = {int(p.floristaID) for p in producciones if p.floristaID is not None}
    nombres = {
        int(f.idFlorista): str(f.nombre)
        for f in db.query(Florista).filter(Florista.idFlorista.in_(list(florista_ids)) if florista_ids else False).all()
    }

    hist_q = db.query(ProduccionHistorial).filter(
        ProduccionHistorial.empresaID == empresa_id,
        ProduccionHistorial.fechaCambio >= datetime.combine(fecha_desde, datetime.min.time()),
        ProduccionHistorial.fechaCambio <= datetime.combine(fecha_hasta, datetime.max.time()),
    )
    if sucursal_id is not None:
        hist_q = hist_q.filter(ProduccionHistorial.sucursalID == sucursal_id)
    historiales = hist_q.all()

    reasignaciones_por_florista: dict[int, int] = {}
    for h in historiales:
        if h.floristaAnteriorID:
            reasignaciones_por_florista[int(h.floristaAnteriorID)] = reasignaciones_por_florista.get(int(h.floristaAnteriorID), 0) + 1

    stats: dict[int, dict] = {}
    for p in producciones:
        if p.floristaID is None:
            continue
        fid = int(p.floristaID)
        bucket = stats.setdefault(fid, {
            "completadas": 0,
            "tiempo_real_sum": 0,
            "tiempo_real_count": 0,
            "cumplidas": 0,
            "reasignaciones": 0,
            "cancelaciones": 0,
        })

        estado = _estado_produccion_norm(p.estado)
        if estado == ESTADO_PARA_ENTREGA:
            bucket["completadas"] += 1
        if p.tiempoRealMin is not None:
            bucket["tiempo_real_sum"] += float(p.tiempoRealMin)
            bucket["tiempo_real_count"] += 1
            if p.tiempoEstimadoMin is not None and float(p.tiempoRealMin) <= float(p.tiempoEstimadoMin):
                bucket["cumplidas"] += 1
        if estado == ESTADO_CANCELADO:
            bucket["cancelaciones"] += 1

    for fid, total in reasignaciones_por_florista.items():
        stats.setdefault(fid, {
            "completadas": 0,
            "tiempo_real_sum": 0,
            "tiempo_real_count": 0,
            "cumplidas": 0,
            "reasignaciones": 0,
            "cancelaciones": 0,
        })["reasignaciones"] = total

    items = []
    for fid, s in sorted(stats.items(), key=lambda x: x[0]):
        tiempo_promedio = (s["tiempo_real_sum"] / s["tiempo_real_count"]) if s["tiempo_real_count"] else 0.0
        cumplimiento = (s["cumplidas"] * 100.0 / s["tiempo_real_count"]) if s["tiempo_real_count"] else 0.0
        items.append(
            FloristaProductividadItem(
                floristaID=fid,
                florista=nombres.get(fid, f"Florista {fid}"),
                completadas=int(s["completadas"]),
                tiempoPromedioRealMin=round(float(tiempo_promedio), 2),
                cumplimientoPct=round(float(cumplimiento), 2),
                reasignaciones=int(s["reasignaciones"]),
                cancelaciones=int(s["cancelaciones"]),
            )
        )

    return FloristaProductividadResponse(items=items)


@router.get("/metricas/operacion", response_model=OperativaDiariaResponse)
def metricas_operacion(
    empresa_id: int = Query(..., alias="empresaID"),
    sucursal_id: int | None = Query(None, alias="sucursalID"),
    fecha_desde: date = Query(..., alias="fechaDesde"),
    fecha_hasta: date = Query(..., alias="fechaHasta"),
    db: Session = Depends(get_db),
):
    q = db.query(Produccion).filter(
        Produccion.empresaID == empresa_id,
        Produccion.fechaProgramadaProduccion >= fecha_desde,
        Produccion.fechaProgramadaProduccion <= fecha_hasta,
    )
    if sucursal_id is not None:
        q = q.filter(Produccion.sucursalID == sucursal_id)

    rows = q.all()

    capacidades = (
        db.query(func.sum(Florista.capacidadDiaria))
        .filter(
            Florista.empresaID == empresa_id,
            Florista.sucursalID == (sucursal_id if sucursal_id is not None else Florista.sucursalID),
            Florista.activo == True,
            func.upper(Florista.estado) == "ACTIVO",
        )
    )
    capacidad_total_base = int(capacidades.scalar() or 0)

    by_date: dict[date, dict] = {}
    for row in rows:
        day = row.fechaProgramadaProduccion
        b = by_date.setdefault(day, {"carga": 0, "retrasos": 0, "completadas": 0})
        if _estado_produccion_norm(row.estado) != ESTADO_CANCELADO:
            b["carga"] += 1
        if row.fechaFinalizacion and row.fechaProgramadaProduccion and row.fechaFinalizacion.date() > row.fechaProgramadaProduccion:
            b["retrasos"] += 1
        if _estado_produccion_norm(row.estado) == ESTADO_PARA_ENTREGA:
            b["completadas"] += 1

    fechas = sorted(by_date.keys())
    promedio = (sum(by_date[d]["completadas"] for d in fechas) / len(fechas)) if fechas else 0.0

    items = []
    for day in fechas:
        carga = int(by_date[day]["carga"])
        capacidad = max(capacidad_total_base, 0)
        utilizacion = (carga * 100.0 / capacidad) if capacidad > 0 else 0.0
        sobrecarga = max(carga - capacidad, 0)

        items.append(
            OperativaDiariaItem(
                fechaProgramadaProduccion=day,
                capacidadTotal=capacidad,
                cargaAsignada=carga,
                capacidadUtilizadaPct=round(float(utilizacion), 2),
                sobrecarga=sobrecarga,
                retrasos=int(by_date[day]["retrasos"]),
                produccionPromedioDiaria=round(float(promedio), 2),
            )
        )

    return OperativaDiariaResponse(items=items)
