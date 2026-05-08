import os
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, func, text
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.core.ordering import sort_operativo
from app.database import get_db
from app.models.cliente import Cliente
from app.models.entrega import Entrega
from app.models.estadopedido import EstadoPedido
from app.models.florista import Florista
from app.models.perfilflorista import PerfilFlorista
from app.models.pedido import Pedido
from app.models.pedidodetalle import PedidoDetalle
from app.models.producto import Producto
from app.models.produccion import Produccion
from app.models.produccionhistorial import ProduccionHistorial
from app.schemas.produccion import (
    AutoAsignacionResponse,
    AutoAsignacionResumen,
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
from app.services import domicilio_service, produccion_service
from app.core.security import (
    assert_same_empresa,
    get_current_auth_context,
    is_empresa_admin_context,
    is_super_admin_context,
    require_module_access,
)

router = APIRouter(
    prefix="/produccion",
    tags=["Produccion"],
    dependencies=[Depends(require_module_access("produccion", "puedeVer"))],
)
produccion_logger = get_logger("produccion")


def _utc_now_naive() -> datetime:
    # These production timestamps are stored in PostgreSQL as timestamp without time zone.
    # Keep writes naive and consistent to avoid subtracting aware vs naive datetimes.
    return datetime.utcnow()


def _activo_truthy(column):
    return func.lower(func.cast(column, String)).in_(["true", "t", "1"])


def _err(code: str, message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "module": "produccion"},
    )


def _require_production_admin(auth=Depends(get_current_auth_context)):
    if not is_empresa_admin_context(auth) and not is_super_admin_context(auth):
        raise HTTPException(status_code=403, detail="Solo administradores pueden ejecutar acciones de producción")
    return auth


def _current_florista_for_user(db: Session, auth) -> Florista | None:
    if getattr(auth, "userID", None) is None:
        return None
    return (
        db.query(Florista)
        .join(PerfilFlorista, PerfilFlorista.empleadoID == Florista.idFlorista)
        .filter(
            Florista.usuarioID == int(auth.userID),
            Florista.empresaID == int(auth.empresaID),
        )
        .first()
    )

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

def _estado_produccion_norm(value: str | int | None, db: Session | None = None) -> str:
    return produccion_service.estado_produccion_norm(value, db=db)


def _estado_florista_norm(value: str | None) -> str:
    return produccion_service.estado_florista_norm(value)


def _numero_pedido_valor(pedido: Pedido) -> int:
    if pedido.numeroPedido is not None:
        return int(pedido.numeroPedido)
    return int(pedido.idPedido)


def _calcular_fecha_programada(fecha_entrega: datetime | None, dias_anticipacion: int) -> date:
    return produccion_service.calcular_fecha_programada(fecha_entrega, dias_anticipacion)


def _is_florista_in_incapacity(florista: Florista, fecha_programada: date) -> bool:
    return produccion_service.is_florista_in_incapacity(florista, fecha_programada)


def _count_carga_florista(db: Session, empresa_id: int, sucursal_id: int, florista_id: int, fecha_programada: date, ignore_produccion_id: int | None = None) -> int:
    return produccion_service.count_carga_florista(
        db=db,
        empresa_id=empresa_id,
        sucursal_id=sucursal_id,
        florista_id=florista_id,
        fecha_programada=fecha_programada,
        ignore_produccion_id=ignore_produccion_id,
    )


def _count_simultaneos_en_produccion(db: Session, empresa_id: int, sucursal_id: int, florista_id: int, ignore_produccion_id: int | None = None) -> int:
    return produccion_service.count_simultaneos_en_produccion(
        db=db,
        empresa_id=empresa_id,
        sucursal_id=sucursal_id,
        florista_id=florista_id,
        ignore_produccion_id=ignore_produccion_id,
    )


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
    return produccion_service.seleccionar_florista_auto(
        db=db,
        empresa_id=empresa_id,
        sucursal_id=sucursal_id,
        fecha_programada=fecha_programada,
        ignore_produccion_id=ignore_produccion_id,
    )


def _calcular_tiempo_estimado_pedido(db: Session, pedido_id: int) -> int:
    return produccion_service.calcular_tiempo_estimado_pedido(db, pedido_id)


def _calcular_tiempo_estimado_detalle(detalle: PedidoDetalle) -> int:
    return produccion_service.calcular_tiempo_estimado_detalle(detalle)


def _entrega_fecha_programada(entrega: Entrega | None) -> datetime | None:
    return produccion_service.entrega_fecha_programada(entrega)


def _log_historial(
    db: Session,
    produccion: Produccion,
    florista_anterior_id: int | None,
    florista_nuevo_id: int | None,
    motivo: str,
    usuario: str,
):
    produccion_service.log_historial(
        db=db,
        produccion=produccion,
        florista_anterior_id=florista_anterior_id,
        florista_nuevo_id=florista_nuevo_id,
        motivo=motivo,
        usuario=usuario,
    )


def _build_producto_map(db: Session, empresa_id: int, produccion_ids: list[int]) -> dict[int, dict[str, str | int | None]]:
    if not produccion_ids:
        return {}

    rows = (
        db.query(
            Produccion.idProduccion,
            PedidoDetalle.idPedidoDetalle,
            Producto.idProducto,
            Producto.codigoProducto,
            Producto.nombreProducto,
            Producto.descripcion,
            PedidoDetalle.observacionesPersonalizados,
        )
        .join(
            PedidoDetalle,
            (PedidoDetalle.idPedidoDetalle == Produccion.pedidoDetalleID)
            & (PedidoDetalle.empresaID == Produccion.empresaID),
        )
        .join(
            Producto,
            (Producto.idProducto == PedidoDetalle.productoID)
            & (Producto.empresaID == Produccion.empresaID),
        )
        .filter(
            Produccion.idProduccion.in_(produccion_ids),
            Produccion.empresaID == empresa_id,
        )
        .all()
    )

    out: dict[int, dict[str, str | int | None]] = {}
    for produccion_id, pedido_detalle_id, producto_id, codigo_producto, nombre_producto, descripcion_producto, observaciones_personalizados in rows:
        key = int(produccion_id)
        observacion_limpia = str(observaciones_personalizados).strip() if observaciones_personalizados else None
        descripcion_limpia = str(descripcion_producto).strip() if descripcion_producto else None
        if observacion_limpia and descripcion_limpia and observacion_limpia.casefold() == descripcion_limpia.casefold():
            observacion_limpia = None
        if key not in out:
            out[key] = {
                "pedidoDetalleID": int(pedido_detalle_id) if pedido_detalle_id is not None else None,
                "productoID": int(producto_id) if producto_id is not None else None,
                "codigoProducto": str(codigo_producto or "").strip() or None,
                "nombreProducto": str(nombre_producto or "Producto"),
                "observacionesPersonalizados": observacion_limpia,
            }
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
        q = q.filter(Produccion.estado == produccion_service.estado_produccion_id(db, estado))
    elif not incluir_cancelado:
        q = q.filter(Produccion.estado != produccion_service.estado_produccion_id(db, ESTADO_CANCELADO))

    rows = q.order_by(Pedido.numeroPedido.asc(), Produccion.idProduccion.asc()).all()
    ids = [int(p.idProduccion) for p, _, _, _, _ in rows]
    producto_map = _build_producto_map(db, empresa_id, ids)

    now_utc = datetime.now(timezone.utc)
    items: list[ProduccionItem] = []

    for produccion, pedido, cliente, entrega, florista in rows:
        fecha_entrega = _entrega_fecha_programada(entrega)
        tiempo_restante_horas = None
        if fecha_entrega:
            delta = fecha_entrega.replace(tzinfo=timezone.utc) - now_utc
            tiempo_restante_horas = int(delta.total_seconds() // 3600)

        producto_info = producto_map.get(int(produccion.idProduccion), {})
        nombre_arreglo = str(producto_info.get("nombreProducto") or "Producto")
        codigo_producto = str(producto_info.get("codigoProducto") or "").strip() or None
        observacion_personalizada = str(producto_info.get("observacionesPersonalizados") or "").strip() or None
        observacion_entrega = str(entrega.observacionGeneral or "").strip() if entrega else ""
        observacion_entrega = observacion_entrega or None
        producto_id = producto_info.get("productoID")
        codigo_arreglo = codigo_producto or (str(producto_id) if producto_id is not None else None)

        items.append(
            ProduccionItem(
                idProduccion=int(produccion.idProduccion),
                pedidoID=int(pedido.idPedido),
                pedidoDetalleID=(
                    int(produccion.pedidoDetalleID)
                    if getattr(produccion, "pedidoDetalleID", None) is not None
                    else producto_info.get("pedidoDetalleID")
                ),
                numeroPedido=_numero_pedido_valor(pedido),
                codigoPedido=(str(pedido.codigoPedido) if pedido.codigoPedido else None),
                floristaID=(int(florista.idFlorista) if florista else None),
                codigoArreglo=codigo_arreglo,
                nombreArreglo=nombre_arreglo,
                producto=nombre_arreglo,
                cliente=str(cliente.nombreCompleto or "Cliente"),
                fechaEntrega=fecha_entrega,
                horaEntrega=(entrega.rangoHora if entrega else None),
                barrio=(str(entrega.barrioNombre or "") if entrega else None) or None,
                observacion=observacion_personalizada,
                notasProduccion=observacion_personalizada,
                observacionesPersonalizados=observacion_entrega,
                floristaAsignado=(florista.nombre if florista else None),
                estado=_estado_produccion_norm(produccion.estado, db=db),
                observaciones=(str(produccion.observacionesInternas).strip() if produccion.observacionesInternas else None),
                fechaAsignacion=produccion.fechaAsignacion,
                tiempoRestanteHoras=tiempo_restante_horas,
                tiempoEstimadoMin=(int(produccion.tiempoEstimadoMin) if produccion.tiempoEstimadoMin is not None else None),
                tiempoRealMin=(int(produccion.tiempoRealMin) if produccion.tiempoRealMin is not None else None),
                prioridad=str(produccion.prioridad or "MEDIA"),
                fechaProgramadaProduccion=produccion.fechaProgramadaProduccion,
            )
        )

    return sorted(
        items,
        key=lambda item: (
            int(item.numeroPedido or 0),
            int(item.idProduccion or 0),
        ),
    )


def _dias_anticipacion_default() -> int:
    return max(int(os.getenv("PRODUCCION_DIAS_ANTICIPACION", "0")), 0)


@router.post("/generar-desde-pedidos", dependencies=[Depends(require_module_access("produccion", "puedeCrear")), Depends(_require_production_admin)])
def generar_desde_pedidos(payload: ProduccionGenerarRequest, db: Session = Depends(get_db), auth=Depends(get_current_auth_context)):
    assert_same_empresa(auth, int(payload.empresaID))
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

    q = db.query(Pedido).filter(Pedido.empresaID == payload.empresaID, Pedido.estadoPedidoID.in_(estado_ids))
    if payload.sucursalID is not None:
        q = q.filter(Pedido.sucursalID == payload.sucursalID)

    created = 0
    for pedido in q.all():
        resumen = produccion_service.asegurar_produccion_desde_pedido_aprobado_por_detalle(
            db=db,
            pedido=pedido,
            dias_anticipacion=dias_anticipacion,
            usuario="produccion.generar_desde_pedidos",
        )
        created += int(resumen.get("createdCount", 0))

    db.commit()
    return {"created": created}


@router.get("/floristas", response_model=FloristaListResponse)
def listar_floristas(
    empresa_id: int = Query(..., alias="empresaID"),
    sucursal_id: int | None = Query(None, alias="sucursalID"),
    solo_activos: bool = Query(True, alias="soloActivos"),
    incluir_externos: bool = Query(False, alias="incluirExternos"),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)
    q = (
        db.query(Florista)
        .join(PerfilFlorista, PerfilFlorista.empleadoID == Florista.idFlorista)
        .filter(Florista.empresaID == empresa_id, func.upper(Florista.cargo) == "FLORISTA")
    )
    if sucursal_id is not None and not incluir_externos:
        q = q.filter(Florista.sucursalID == sucursal_id)
    if solo_activos:
        q = q.filter(_activo_truthy(Florista.activo))

    rows = q.order_by(Florista.nombre.asc()).all()

    florista_ids = [int(row.idFlorista) for row in rows]
    arreglos_hoy_por_florista: dict[int, int] = {}
    if florista_ids:
        estado_cancelado_id = produccion_service.estado_produccion_id(db, ESTADO_CANCELADO)
        arreglos_rows = (
            db.query(Produccion.floristaID, func.count(Produccion.idProduccion))
            .filter(
                Produccion.empresaID == empresa_id,
                Produccion.floristaID.in_(florista_ids),
                Produccion.fechaProgramadaProduccion == date.today(),
                Produccion.estado != estado_cancelado_id,
            )
            .group_by(Produccion.floristaID)
            .all()
        )
        arreglos_hoy_por_florista = {int(fid): int(total or 0) for fid, total in arreglos_rows if fid is not None}

    internos: list[Florista] = []
    externos: list[Florista] = []
    if sucursal_id is not None and incluir_externos:
        for row in rows:
            if row.sucursalID is not None and int(row.sucursalID) == int(sucursal_id):
                internos.append(row)
            else:
                externos.append(row)
    else:
        internos = list(rows)

    ordered_rows = internos + externos

    return FloristaListResponse(
        items=[
            FloristaItem(
                idFlorista=int(row.idFlorista),
                usuarioID=(int(row.usuarioID) if getattr(row, "usuarioID", None) is not None else None),
                nombre=str(row.nombre),
                numeroFlorista=(int(row.numeroInterno) if getattr(row, "numeroInterno", None) is not None else None),
                esExterno=bool(index >= len(internos)),
                arreglosHoy=int(arreglos_hoy_por_florista.get(int(row.idFlorista), 0)),
                capacidadDiaria=int(row.capacidadDiaria or 0),
                trabajosSimultaneosPermitidos=int(row.trabajosSimultaneosPermitidos or 1),
                estado=_estado_florista_norm(row.estado),
                fechaInicioIncapacidad=row.fechaInicioIncapacidad,
                fechaFinIncapacidad=row.fechaFinIncapacidad,
                activo=bool(row.activo),
                especialidades=row.especialidades,
            )
            for index, row in enumerate(ordered_rows)
        ]
    )


@router.put("/floristas/{florista_id}/estado", dependencies=[Depends(require_module_access("produccion", "puedeEditar"))])
def actualizar_estado_florista(florista_id: int, payload: FloristaEstadoRequest, db: Session = Depends(get_db), auth=Depends(get_current_auth_context)):
    florista = db.query(Florista).filter(Florista.idFlorista == florista_id).first()
    if not florista:
        produccion_logger.warning("Florista no encontrado. florista_id=%s", florista_id)
        raise _err("PRODUCCION_FLORISTA_NOT_FOUND", "Florista no encontrado", status_code=404)
    assert_same_empresa(auth, int(florista.empresaID))

    nuevo_estado = _estado_florista_norm(payload.estado)
    if not is_empresa_admin_context(auth) and not is_super_admin_context(auth):
        current_florista = _current_florista_for_user(db, auth)
        if current_florista:
            current_florista_id = int(current_florista.idFlorista or 0)
            actual_florista_id = int(produccion.floristaID or 0)
            destino_florista_id = int(payload.floristaNuevoID or 0)
            takeover_allowed = (
                (actual_florista_id == 0 and destino_florista_id == current_florista_id)
                or (actual_florista_id != 0 and destino_florista_id == current_florista_id)
            )
            if takeover_allowed:
                class _FloristaGuard:
                    def __init__(self, florista_id: int):
                        self.idFlorista = florista_id
                current_florista = _FloristaGuard(actual_florista_id)
        if not current_florista or int(current_florista.idFlorista) != int(florista_id):
            raise HTTPException(status_code=403, detail="Solo puedes actualizar tu propio estado de florista")
        if nuevo_estado not in {"Activo", "Inactivo"}:
            raise HTTPException(status_code=400, detail="Para floristas solo se permite Activo o Inactivo")
    if nuevo_estado not in {"Activo", "Inactivo", "Incapacidad"}:
        raise HTTPException(status_code=400, detail="Estado de florista inválido")

    activo_flag = int(1 if nuevo_estado == "Activo" else 0)
    now_utc = _utc_now_naive()
    db.execute(
        text(
            """
            UPDATE petalops.empleado
            SET activo = :activo,
                updated_at = :updated_at
            WHERE id_empleado = :florista_id
            """
        ),
        {
            "activo": activo_flag,
            "updated_at": now_utc,
            "florista_id": int(florista.idFlorista),
        },
    )
    db.expire(florista)

    perfil = db.query(PerfilFlorista).filter(PerfilFlorista.empleadoID == florista.idFlorista).first()
    if not perfil:
        perfil = PerfilFlorista(
            empleadoID=int(florista.idFlorista),
            capacidadDiaria=max(int(florista.capacidadDiaria or 1), 1),
            trabajosSimultaneosPermitidos=max(int(florista.trabajosSimultaneosPermitidos or 1), 1),
            especialidades=florista.especialidades,
        )
        db.add(perfil)
        db.flush()

    if nuevo_estado == "Incapacidad":
        perfil.fechaInicioIncapacidad = payload.fechaInicioIncapacidad or date.today()
        perfil.fechaFinIncapacidad = payload.fechaFinIncapacidad
    else:
        perfil.fechaInicioIncapacidad = None
        perfil.fechaFinIncapacidad = None

    reasignadas = 0
    sin_reemplazo = 0
    requiere_manual = 0

    if nuevo_estado == "Incapacidad":
        resumen = produccion_service.reasignar_pendientes_por_indisponibilidad(
            db=db,
            florista=florista,
            usuario=payload.usuarioCambio,
            motivo=(payload.motivo or f"Reasignación automática por {nuevo_estado.lower()} del florista"),
        )
        reasignadas = int(resumen["reasignadas"])
        sin_reemplazo = int(resumen["sinReemplazo"])

        requiere_manual = int(
            db.query(func.count(Produccion.idProduccion))
            .filter(
                Produccion.empresaID == florista.empresaID,
                Produccion.sucursalID == florista.sucursalID,
                Produccion.floristaID == florista.idFlorista,
                Produccion.estado == produccion_service.estado_produccion_id(db, ESTADO_EN_PRODUCCION),
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
        "pendientesSinReemplazo": sin_reemplazo,
        "enProduccionRequierenAccionManual": requiere_manual,
    }


@router.post("/floristas/sincronizar-incapacidades", dependencies=[Depends(require_module_access("produccion", "puedeEditar")), Depends(_require_production_admin)])
def sincronizar_incapacidades(
    empresa_id: int = Query(..., alias="empresaID"),
    sucursal_id: int | None = Query(None, alias="sucursalID"),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)
    resumen = produccion_service.sincronizar_incapacidades_y_reasignar(
        db=db,
        empresa_id=empresa_id,
        sucursal_id=sucursal_id,
        usuario="job.sincronizar_incapacidades",
    )
    db.commit()
    return {"status": "ok", **resumen}


@router.get("", response_model=ProduccionListResponse)
def listar_produccion(
    empresa_id: int = Query(..., alias="empresaID"),
    sucursal_id: int | None = Query(None, alias="sucursalID"),
    fecha: date | None = Query(None),
    estado: str | None = Query(None),
    incluir_cancelado: bool = Query(False, alias="incluirCancelado"),
    auto_asignar_pendientes_hoy: bool = Query(True, alias="autoAsignarPendientesHoy"),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)
    target_fecha = fecha
    auto_resumen = AutoAsignacionResumen(
        ejecutada=False,
        evaluadas=0,
        asignadas=0,
        sinDisponibilidad=0,
    )

    if auto_asignar_pendientes_hoy:
        stats = produccion_service.asignar_pendientes_por_fecha(
            db=db,
            empresa_id=empresa_id,
            fecha_objetivo=date.today(),
            sucursal_id=sucursal_id,
            incluir_vencidas=False,
            usuario="produccion.listar",
            motivo="Asignación automática al abrir módulo Producción (hoy)",
        )
        db.commit()
        auto_resumen = AutoAsignacionResumen(
            ejecutada=True,
            evaluadas=int(stats["evaluadas"]),
            asignadas=int(stats["asignadas"]),
            sinDisponibilidad=int(stats["sinDisponibilidad"]),
        )

    items = _build_items(
        db=db,
        empresa_id=empresa_id,
        sucursal_id=sucursal_id,
        fecha_programada=target_fecha,
        estado=estado,
        incluir_cancelado=incluir_cancelado,
    )
    return ProduccionListResponse(items=items, total=len(items), autoAsignacion=auto_resumen)


@router.post("/asignar-pendientes-hoy", response_model=AutoAsignacionResponse, dependencies=[Depends(require_module_access("produccion", "puedeEditar"))])
def asignar_pendientes_hoy(
    empresa_id: int = Query(..., alias="empresaID"),
    sucursal_id: int | None = Query(None, alias="sucursalID"),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)
    stats = produccion_service.asignar_pendientes_hoy(
        db=db,
        empresa_id=empresa_id,
        sucursal_id=sucursal_id,
        usuario="produccion.asignar_pendientes_hoy",
        motivo="Asignación manual de pendientes de hoy",
    )
    db.commit()

    return AutoAsignacionResponse(
        status="ok",
        fecha=date.today(),
        empresaID=empresa_id,
        sucursalID=sucursal_id,
        evaluadas=int(stats["evaluadas"]),
        asignadas=int(stats["asignadas"]),
        sinDisponibilidad=int(stats["sinDisponibilidad"]),
    )



@router.post(
    "/asignar-pendientes-fecha",
    response_model=AutoAsignacionResponse,
    dependencies=[Depends(require_module_access("produccion", "puedeEditar")), Depends(_require_production_admin)],
)
def asignar_pendientes_por_fecha(
    empresa_id: int = Query(..., alias="empresaID"),
    fecha: date = Query(...),
    sucursal_id: int | None = Query(None, alias="sucursalID"),
    incluir_vencidas: bool = Query(False, alias="incluirVencidas"),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)
    if fecha > date.today():
        raise HTTPException(status_code=400, detail="Solo se permiten fechas de hoy o anteriores")

    stats = produccion_service.asignar_pendientes_por_fecha(
        db=db,
        empresa_id=empresa_id,
        fecha_objetivo=fecha,
        sucursal_id=sucursal_id,
        incluir_vencidas=incluir_vencidas,
        usuario="produccion.asignar_pendientes_fecha",
        motivo=(
            "Asignación manual de pendientes hasta fecha objetivo"
            if incluir_vencidas
            else "Asignación manual de pendientes por fecha objetivo"
        ),
    )
    db.commit()

    return AutoAsignacionResponse(
        status="ok",
        fecha=fecha,
        empresaID=empresa_id,
        sucursalID=sucursal_id,
        evaluadas=int(stats["evaluadas"]),
        asignadas=int(stats["asignadas"]),
        sinDisponibilidad=int(stats["sinDisponibilidad"]),
    )


@router.get("/resumen", response_model=ProduccionResumenResponse)
def resumen_produccion(
    empresa_id: int = Query(..., alias="empresaID"),
    sucursal_id: int | None = Query(None, alias="sucursalID"),
    fecha: date | None = Query(None),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)
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
        key = _estado_produccion_norm(item.estado, db=db)
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
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)
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
        grouped[_estado_produccion_norm(item.estado, db=db)].append(item)

    return ProduccionKanbanResponse(
        pendiente=grouped[ESTADO_PENDIENTE],
        enProduccion=grouped[ESTADO_EN_PRODUCCION],
        paraEntrega=grouped[ESTADO_PARA_ENTREGA],
        cancelado=grouped[ESTADO_CANCELADO],
    )


@router.put("/{produccion_id}/asignar", dependencies=[Depends(require_module_access("produccion", "puedeEditar")), Depends(_require_production_admin)])
def asignar_produccion(produccion_id: int, payload: ProduccionAsignarRequest, db: Session = Depends(get_db), auth=Depends(get_current_auth_context)):
    produccion = db.query(Produccion).filter(Produccion.idProduccion == produccion_id).first()
    if not produccion:
        produccion_logger.warning("Producción no encontrada. produccion_id=%s", produccion_id)
        raise _err("PRODUCCION_NOT_FOUND", "Registro de producción no encontrado", status_code=404)
    assert_same_empresa(auth, int(produccion.empresaID))

    fecha_programada = payload.fechaProgramadaProduccion or produccion.fechaProgramadaProduccion
    if not fecha_programada:
        raise HTTPException(status_code=400, detail="fechaProgramadaProduccion es obligatoria")
    if fecha_programada > date.today():
        raise HTTPException(status_code=400, detail="No se permite asignar producciones con fecha futura")

    estado_actual = _estado_produccion_norm(produccion.estado, db=db)
    if estado_actual == ESTADO_EN_PRODUCCION and not (payload.motivo and payload.usuarioCambio):
        raise HTTPException(status_code=400, detail="Para reasignar en EnProduccion debes indicar motivo y usuarioCambio")

    if payload.floristaID is not None:
        florista = (
            db.query(Florista)
            .join(PerfilFlorista, PerfilFlorista.empleadoID == Florista.idFlorista)
            .filter(
                Florista.idFlorista == payload.floristaID,
                Florista.empresaID == produccion.empresaID,
                Florista.sucursalID == produccion.sucursalID,
            )
            .first()
        )
        if not florista:
            produccion_logger.warning("Florista no encontrado. florista_id=%s", payload.floristaID)
            raise _err("PRODUCCION_FLORISTA_NOT_FOUND", "Florista no encontrado", status_code=404)
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
    now_utc = _utc_now_naive()

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


@router.put("/{produccion_id}/reasignar", dependencies=[Depends(require_module_access("produccion", "puedeEditar"))])
def reasignar_produccion(produccion_id: int, payload: ProduccionReasignarRequest, db: Session = Depends(get_db), auth=Depends(get_current_auth_context)):
    usuario_cambio = str(payload.usuarioCambio or auth.login or auth.nombre or "system").strip()
    if not usuario_cambio:
        usuario_cambio = "system"
    motivo = str(payload.motivo or "").strip() or "Reasignación desde panel de producción"

    if not is_empresa_admin_context(auth) and not is_super_admin_context(auth):
        produccion = db.query(Produccion).filter(Produccion.idProduccion == produccion_id).first()
        if not produccion:
            raise _err("PRODUCCION_NOT_FOUND", "Registro de producciÃ³n no encontrado", status_code=404)
        assert_same_empresa(auth, int(produccion.empresaID))
        current_florista = _current_florista_for_user(db, auth)
        if not current_florista or int(produccion.floristaID or 0) != int(current_florista.idFlorista):
            raise HTTPException(status_code=403, detail="Solo puedes reasignar producciones que hoy estÃ¡n asignadas a ti")

    wrapper = ProduccionAsignarRequest(
        floristaID=payload.floristaNuevoID,
        fechaProgramadaProduccion=payload.fechaProgramadaProduccion,
        motivo=motivo,
        usuarioCambio=usuario_cambio,
    )
    return asignar_produccion(produccion_id, wrapper, db, auth)


@router.put("/{produccion_id}/estado", dependencies=[Depends(require_module_access("produccion", "puedeEditar"))])
def cambiar_estado_produccion(produccion_id: int, payload: ProduccionEstadoRequest, db: Session = Depends(get_db), auth=Depends(get_current_auth_context)):
    if is_empresa_admin_context(auth) and not is_super_admin_context(auth):
        raise HTTPException(status_code=403, detail="Acción no disponible para rol Administrador")

    produccion = db.query(Produccion).filter(Produccion.idProduccion == produccion_id).first()
    if not produccion:
        produccion_logger.warning("Producción no encontrada. produccion_id=%s", produccion_id)
        raise _err("PRODUCCION_NOT_FOUND", "Registro de producción no encontrado", status_code=404)
    assert_same_empresa(auth, int(produccion.empresaID))

    estado_actual = _estado_produccion_norm(produccion.estado, db=db)
    nuevo_estado = _estado_produccion_norm(payload.nuevoEstado, db=db)

    if nuevo_estado not in ESTADOS_VALIDOS:
        raise HTTPException(status_code=400, detail=f"Estado inválido. Usa: {', '.join(sorted(ESTADOS_VALIDOS))}")

    if nuevo_estado == estado_actual:
        return {"status": "ok", "idProduccion": produccion_id, "estado": estado_actual}

    if domicilio_service.is_produccion_bloqueada_por_entrega_en_ruta(db, int(produccion.idProduccion)):
        raise HTTPException(status_code=400, detail="No se permite modificar Producción cuando el domicilio está EnRuta")

    if not produccion_service.transicion_produccion_permitida(
        db=db,
        empresa_id=int(produccion.empresaID),
        origen=produccion.estado,
        destino=nuevo_estado,
    ):
        raise HTTPException(status_code=400, detail=f"Transición no permitida: {estado_actual} -> {nuevo_estado}")

    if nuevo_estado == ESTADO_EN_PRODUCCION:
        if not produccion.floristaID:
            raise HTTPException(status_code=400, detail="No puedes iniciar producción sin florista asignado")

        florista = (
            db.query(Florista)
            .join(PerfilFlorista, PerfilFlorista.empleadoID == Florista.idFlorista)
            .filter(Florista.idFlorista == produccion.floristaID)
            .first()
        )
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

    now_utc = _utc_now_naive()
    produccion.estado = produccion_service.estado_produccion_id(db, nuevo_estado)

    if nuevo_estado == ESTADO_EN_PRODUCCION and not produccion.fechaInicio:
        produccion.fechaInicio = now_utc
    if nuevo_estado == ESTADO_PARA_ENTREGA:
        if not produccion.fechaInicio:
            produccion.fechaInicio = now_utc
        produccion.fechaFinalizacion = now_utc
        delta_min = int((produccion.fechaFinalizacion - produccion.fechaInicio).total_seconds() // 60)
        produccion.tiempoRealMin = max(delta_min, 0)

        pedido = db.query(Pedido).filter(Pedido.idPedido == produccion.pedidoID).first()
        domicilio_service.ensure_entrega_desde_produccion(db=db, produccion=produccion, pedido=pedido)

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


@router.post("/pedido/{pedido_id}/recalcular", dependencies=[Depends(require_module_access("produccion", "puedeEditar")), Depends(_require_production_admin)])
def recalcular_produccion_por_pedido(pedido_id: int, payload: ProduccionRecalcularPedidoRequest, db: Session = Depends(get_db), auth=Depends(get_current_auth_context)):
    if is_empresa_admin_context(auth) and not is_super_admin_context(auth):
        raise HTTPException(status_code=403, detail="Acción no disponible para rol Administrador")

    pedido = db.query(Pedido).filter(Pedido.idPedido == pedido_id).first()
    if not pedido:
        produccion_logger.warning("Pedido no encontrado. pedido_id=%s", pedido_id)
        raise _err("PRODUCCION_PEDIDO_NOT_FOUND", "Pedido no encontrado", status_code=404)
    assert_same_empresa(auth, int(pedido.empresaID))

    producciones = (
        db.query(Produccion)
        .filter(
            Produccion.pedidoID == pedido_id,
            Produccion.empresaID == int(pedido.empresaID),
        )
        .order_by(Produccion.idProduccion.desc())
        .all()
    )
    if not producciones:
        raise _err("PRODUCCION_NOT_FOUND", "No existe producción asociada al pedido", status_code=404)

    entrega = db.query(Entrega).filter(Entrega.pedidoID == pedido_id).first()
    detalle_rows = (
        db.query(PedidoDetalle)
        .filter(
            PedidoDetalle.empresaID == int(pedido.empresaID),
            PedidoDetalle.pedidoID == int(pedido.idPedido),
        )
        .order_by(PedidoDetalle.idPedidoDetalle.asc())
        .all()
    )
    if not detalle_rows:
        raise HTTPException(status_code=400, detail="El pedido no tiene detalles para recalcular producción")

    detalle_by_id = {int(det.idPedidoDetalle): det for det in detalle_rows}
    fecha_programada = _calcular_fecha_programada(_entrega_fecha_programada(entrega), _dias_anticipacion_default())
    estados_actuales = {_estado_produccion_norm(prod.estado, db=db) for prod in producciones}

    for produccion in producciones:
        if domicilio_service.is_produccion_bloqueada_por_entrega_en_ruta(db, int(produccion.idProduccion)):
            raise HTTPException(status_code=400, detail="No se puede recalcular producción: el domicilio ya está EnRuta")

    now_utc = _utc_now_naive()

    if estados_actuales == {ESTADO_PENDIENTE}:
        for produccion in producciones:
            detalle = detalle_by_id.get(int(produccion.pedidoDetalleID or 0))
            if detalle is None and len(detalle_rows) == 1:
                detalle = detalle_rows[0]
                produccion.pedidoDetalleID = int(detalle.idPedidoDetalle)

            produccion.tiempoEstimadoMin = (
                _calcular_tiempo_estimado_detalle(detalle) if detalle is not None else _calcular_tiempo_estimado_pedido(db, pedido_id)
            )
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

            produccion.updatedAt = now_utc

        pedido.version = int(pedido.version or 1) + 1
        db.commit()
        return {
            "status": "ok",
            "modo": "recalculado_pendiente",
            "versionPedido": int(pedido.version),
            "produccionesActualizadas": len(producciones),
        }

    if ESTADO_EN_PRODUCCION in estados_actuales:
        if not payload.productoEstructuralCambiado and not payload.forceCancelarYCrearNueva:
            raise HTTPException(status_code=400, detail="En EnProduccion no se permite cambio estructural sin cancelar y recrear")

        pedido.version = int(pedido.version or 1) + 1
        prioridad_referencia = str(producciones[0].prioridad or "MEDIA")

        for produccion in producciones:
            produccion.estado = produccion_service.estado_produccion_id(db, ESTADO_CANCELADO)
            produccion.observacionesInternas = (
                (produccion.observacionesInternas or "")
                + f"\nCancelado por cambio estructural del pedido v{int(pedido.version)}."
            )
            produccion.updatedAt = now_utc

        db.flush()

        resumen = produccion_service.asegurar_produccion_desde_pedido_aprobado_por_detalle(
            db=db,
            pedido=pedido,
            dias_anticipacion=_dias_anticipacion_default(),
            usuario=payload.usuarioCambio,
        )

        for item in resumen.get("producciones", []):
            if not item.get("created"):
                continue
            nueva = db.query(Produccion).filter(Produccion.idProduccion == int(item["produccionID"])).first()
            if nueva:
                nueva.prioridad = prioridad_referencia
                nueva.observacionesInternas = f"Nueva producción por cambio estructural pedido v{pedido.version}"
                nueva.updatedAt = now_utc

        db.commit()
        return {
            "status": "ok",
            "modo": "cancelada_y_recreada",
            "versionPedido": int(pedido.version),
            "createdCount": int(resumen.get("createdCount", 0)),
        }

    raise HTTPException(status_code=400, detail="Solo se puede recalcular en Pendiente o EnProduccion")


@router.get("/historial/reasignaciones", response_model=ReasignacionHistorialResponse)
def historial_reasignaciones(
    empresa_id: int = Query(..., alias="empresaID"),
    sucursal_id: int | None = Query(None, alias="sucursalID"),
    fecha_desde: date = Query(..., alias="fechaDesde"),
    fecha_hasta: date = Query(..., alias="fechaHasta"),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)
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


@router.get("/trazabilidad/usuarios", dependencies=[Depends(require_module_access("trazabilidad", "puedeVer"))])
def trazabilidad_usuarios_produccion(
    empresa_id: int = Query(..., alias="empresaID"),
    sucursal_id: int | None = Query(None, alias="sucursalID"),
    fecha_desde: date = Query(..., alias="fechaDesde"),
    fecha_hasta: date = Query(..., alias="fechaHasta"),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, int(empresa_id))

    q = (
        db.query(
            ProduccionHistorial,
            Produccion.pedidoID,
            Pedido.numeroPedido,
            Pedido.codigoPedido,
            Cliente.nombreCompleto,
        )
        .join(
            Produccion,
            (Produccion.idProduccion == ProduccionHistorial.produccionID)
            & (Produccion.empresaID == ProduccionHistorial.empresaID),
        )
        .outerjoin(
            Pedido,
            (Pedido.idPedido == Produccion.pedidoID)
            & (Pedido.empresaID == Produccion.empresaID),
        )
        .outerjoin(
            Cliente,
            (Cliente.idCliente == Pedido.clienteID)
            & (Cliente.empresaID == Pedido.empresaID),
        )
        .filter(
            ProduccionHistorial.empresaID == int(empresa_id),
            ProduccionHistorial.fechaCambio >= datetime.combine(fecha_desde, datetime.min.time()),
            ProduccionHistorial.fechaCambio <= datetime.combine(fecha_hasta, datetime.max.time()),
        )
    )
    if sucursal_id is not None:
        q = q.filter(ProduccionHistorial.sucursalID == int(sucursal_id))

    rows = q.order_by(ProduccionHistorial.fechaCambio.desc()).all()

    resumen: dict[str, dict] = {}
    detalle = []
    for historial, pedido_id, numero_pedido, codigo_pedido, cliente_nombre in rows:
        usuario = str(historial.usuarioCambio or "system").strip() or "system"
        bucket = resumen.setdefault(
            usuario,
            {
                "usuario": usuario,
                "acciones": 0,
                "producciones": set(),
                "pedidos": set(),
                "ultimoMovimiento": None,
            },
        )
        bucket["acciones"] += 1
        bucket["producciones"].add(int(historial.produccionID))
        if pedido_id is not None:
            bucket["pedidos"].add(int(pedido_id))
        if bucket["ultimoMovimiento"] is None or historial.fechaCambio > bucket["ultimoMovimiento"]:
            bucket["ultimoMovimiento"] = historial.fechaCambio

        detalle.append(
            {
                "usuario": usuario,
                "produccionID": int(historial.produccionID),
                "pedidoID": (int(pedido_id) if pedido_id is not None else None),
                "numeroPedido": (int(numero_pedido) if numero_pedido is not None else None),
                "codigoPedido": (str(codigo_pedido or "").strip() or None),
                "cliente": str(cliente_nombre or "-"),
                "motivo": str(historial.motivo or "").strip(),
                "fechaAccion": historial.fechaCambio,
                "floristaAnteriorID": (int(historial.floristaAnteriorID) if historial.floristaAnteriorID is not None else None),
                "floristaNuevoID": (int(historial.floristaNuevoID) if historial.floristaNuevoID is not None else None),
            }
        )

    resumen_items = sorted(
        [
            {
                "usuario": data["usuario"],
                "accionesRegistradas": int(data["acciones"]),
                "produccionesImpactadas": len(data["producciones"]),
                "pedidosImpactados": len(data["pedidos"]),
                "ultimoMovimiento": data["ultimoMovimiento"],
            }
            for data in resumen.values()
        ],
        key=lambda item: (-int(item["accionesRegistradas"]), item["usuario"]),
    )

    return {
        "resumen": resumen_items,
        "detalle": detalle,
        "total": len(detalle),
    }


@router.get("/metricas/productividad", response_model=FloristaProductividadResponse)
def metricas_productividad(
    empresa_id: int = Query(..., alias="empresaID"),
    sucursal_id: int | None = Query(None, alias="sucursalID"),
    fecha_desde: date = Query(..., alias="fechaDesde"),
    fecha_hasta: date = Query(..., alias="fechaHasta"),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)
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

        estado = _estado_produccion_norm(p.estado, db=db)
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
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)
    q = db.query(Produccion).filter(
        Produccion.empresaID == empresa_id,
        Produccion.fechaProgramadaProduccion >= fecha_desde,
        Produccion.fechaProgramadaProduccion <= fecha_hasta,
    )
    if sucursal_id is not None:
        q = q.filter(Produccion.sucursalID == sucursal_id)

    rows = q.all()

    # En el esquema actual no existe tabla florista; derivamos capacidad desde producción:
    # número de empleados asignados únicos por día (mínimo 1 por empleado).
    capacidad_por_dia: dict[date, int] = {}
    for row in rows:
        if row.fechaProgramadaProduccion is None:
            continue
        day = row.fechaProgramadaProduccion
        if day not in capacidad_por_dia:
            capacidad_por_dia[day] = 0
    for day in list(capacidad_por_dia.keys()):
        asignados = {
            int(r.floristaID)
            for r in rows
            if r.fechaProgramadaProduccion == day and r.floristaID is not None
        }
        capacidad_por_dia[day] = len(asignados)

    by_date: dict[date, dict] = {}
    for row in rows:
        day = row.fechaProgramadaProduccion
        b = by_date.setdefault(day, {"carga": 0, "retrasos": 0, "completadas": 0})
        if _estado_produccion_norm(row.estado, db=db) != ESTADO_CANCELADO:
            b["carga"] += 1
        if row.fechaFinalizacion and row.fechaProgramadaProduccion and row.fechaFinalizacion.date() > row.fechaProgramadaProduccion:
            b["retrasos"] += 1
        if _estado_produccion_norm(row.estado, db=db) == ESTADO_PARA_ENTREGA:
            b["completadas"] += 1

    fechas = sorted(by_date.keys())
    promedio = (sum(by_date[d]["completadas"] for d in fechas) / len(fechas)) if fechas else 0.0

    items = []
    for day in fechas:
        carga = int(by_date[day]["carga"])
        capacidad = max(int(capacidad_por_dia.get(day, 0)), 0)
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
