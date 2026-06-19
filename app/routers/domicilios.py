from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4
import os
import shutil

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import String, and_, cast, func, or_
from sqlalchemy.orm import Session, aliased

from app.core.logger import get_logger
from app.core.ordering import sort_operativo
from app.core.security import (
    assert_same_empresa,
    get_current_auth_context,
    is_empresa_admin_context,
    is_super_admin_context,
    require_module_access,
)
from app.database import get_db
from app.models.cliente import Cliente
from app.models.domiciliario import Domiciliario
from app.models.entrega import Entrega
from app.models.pedido import Pedido
from app.models.produccion import Produccion
from app.schemas.domicilios import (
    AsignarDomiciliarioRequest,
    DomiciliarioItem,
    DomiciliarioListResponse,
    DomicilioActionResponse,
    DomicilioAdminItem,
    DomicilioAdminListResponse,
    DomicilioCourierCard,
    DomicilioCourierListResponse,
    ESTADO_ASIGNADO,
    ESTADO_EN_RUTA,
    ESTADO_ENTREGADO,
    ESTADO_NO_ENTREGADO,
    ESTADO_PENDIENTE,
    MarcarEnRutaRequest,
    MarcarNoEntregadoRequest,
    TomarEntregaRequest,
)
from app.services import domicilio_service, produccion_service

router = APIRouter(
    prefix="/domicilios",
    tags=["Domicilios"],
    dependencies=[Depends(require_module_access("domicilios", "puedeVer"))],
)
domicilios_logger = get_logger("domicilios")


def _activo_truthy(column):
    return func.lower(cast(column, String)).in_(["true", "t", "1"])


def _err(code: str, message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "module": "domicilios"},
    )


def _numero_pedido_valor(pedido: Pedido) -> int:
    if pedido.numeroPedido is not None:
        return int(pedido.numeroPedido)
    return int(pedido.idPedido)


def _domiciliario_id_for_auth(db: Session, auth) -> int | None:
    return domicilio_service.find_domiciliario_id_for_user(db, auth)


def _assert_auth_domiciliario(db: Session, auth) -> int:
    domic_id = _domiciliario_id_for_auth(db, auth)
    if domic_id is None:
        raise _err(
            "DOMICILIO_USER_NOT_LINKED",
            "No se pudo resolver el domiciliario para el usuario autenticado",
            status_code=403,
        )
    return domic_id


def _actor_can_override_delivery(auth) -> bool:
    return is_super_admin_context(auth) or is_empresa_admin_context(auth)


def _latest_entrega_id_subquery(db: Session, empresa_id: int):
    latest_attempt_sq = (
        db.query(
            Entrega.pedidoID.label("pedido_id"),
            func.max(Entrega.intentoNumero).label("max_intento"),
        )
        .filter(Entrega.empresaID == int(empresa_id))
        .group_by(Entrega.pedidoID)
        .subquery()
    )

    return (
        db.query(
            Entrega.pedidoID.label("pedido_id"),
            func.max(Entrega.idEntrega).label("entrega_id"),
        )
        .join(
            latest_attempt_sq,
            and_(
                Entrega.pedidoID == latest_attempt_sq.c.pedido_id,
                Entrega.intentoNumero == latest_attempt_sq.c.max_intento,
            ),
        )
        .filter(Entrega.empresaID == int(empresa_id))
        .group_by(Entrega.pedidoID)
        .subquery()
    )


def _locked_current_entrega(db: Session, empresa_id: int, entrega_id: int) -> Entrega:
    entrega = (
        db.query(Entrega)
        .filter(
            Entrega.idEntrega == int(entrega_id),
            Entrega.empresaID == int(empresa_id),
        )
        .with_for_update()
        .first()
    )
    if not entrega:
        raise _err("DOMICILIO_NOT_FOUND", "Entrega no encontrada", status_code=404)

    current_entrega = (
        db.query(Entrega)
        .filter(
            Entrega.empresaID == int(empresa_id),
            Entrega.pedidoID == int(entrega.pedidoID),
        )
        .order_by(Entrega.intentoNumero.desc(), Entrega.idEntrega.desc())
        .with_for_update()
        .first()
    )
    if not current_entrega or int(current_entrega.idEntrega) != int(entrega.idEntrega):
        raise _err(
            "DOMICILIO_STALE_ATTEMPT",
            "La entrega ya no es el intento vigente del pedido",
            status_code=409,
        )
    return current_entrega


def _assert_entrega_actor_scope(entrega: Entrega, auth, db: Session):
    if _actor_can_override_delivery(auth):
        return

    actor_domiciliario_id = _domiciliario_id_for_auth(db, auth)
    if actor_domiciliario_id is None:
        return

    if entrega.domiciliarioID is None or int(entrega.domiciliarioID) != int(actor_domiciliario_id):
        raise _err(
            "DOMICILIO_NOT_ASSIGNED_TO_ACTOR",
            "La entrega no está asignada al domiciliario autenticado",
            status_code=403,
        )


def _save_upload_file(upload: UploadFile | None) -> str | None:
    if not upload or not upload.filename:
        return None

    root = Path(os.getenv("DOMICILIO_UPLOAD_ROOT", "uploads"))
    root.mkdir(parents=True, exist_ok=True)
    extension = Path(upload.filename).suffix or ""
    target = root / f"{uuid4().hex}{extension}"
    with target.open("wb") as buffer:
        shutil.copyfileobj(upload.file, buffer)

    base_url = os.getenv("DOMICILIO_UPLOAD_BASE_URL")
    if base_url:
        return f"{base_url.rstrip('/')}/{target.name}"
    return str(target.resolve())


def _build_courier_card(
    entrega: Entrega,
    pedido: Pedido,
    cliente: Cliente | None,
    produccion: Produccion | None,
    distancia_km: float | None = None,
) -> DomicilioCourierCard:
    lat_destino, lng_destino = domicilio_service.payload_destino_lat_lng(entrega)
    lat, lng = domicilio_service.payload_lat_lng(entrega)
    return DomicilioCourierCard(
        idEntrega=int(entrega.idEntrega),
        pedidoID=int(entrega.pedidoID),
        numeroPedido=_numero_pedido_valor(pedido),
        codigoPedido=(str(pedido.codigoPedido) if pedido.codigoPedido else None),
        cliente=(str(cliente.nombreCompleto or "Cliente") if cliente else None),
        destinatario=str(entrega.destinatario or "") or None,
        direccion=str(entrega.direccion or "") or None,
        barrio=str(entrega.barrioNombre or "") or None,
        telefonoDestino=str(entrega.telefonoDestino or "") or None,
        mensaje=str(entrega.mensaje or "") or None,
        observacion=(str(entrega.observacionGeneral or entrega.observaciones or "").strip() or None),
        estado=domicilio_service.estado_norm(entrega.estadoEntregaID),
        horaEntrega=str(entrega.rangoHora or "") or None,
        fechaEntregaProgramada=(entrega.reprogramadaPara or entrega.fechaEntregaProgramada or entrega.fechaEntrega),
        prioridad=(str(produccion.prioridad or "") if produccion and produccion.prioridad else None),
        latitudDestino=lat_destino,
        longitudDestino=lng_destino,
        latitudEntrega=lat,
        longitudEntrega=lng,
        distanciaKm=distancia_km,
    )


def _build_mis_entregas_query(
    db: Session,
    empresa_id: int,
    sucursal_id: int | None,
    domiciliario_id: int,
    fecha: date,
):
    start = datetime.combine(fecha, datetime.min.time())
    end = datetime.combine(fecha, datetime.max.time())
    latest_entrega_sq = _latest_entrega_id_subquery(db, empresa_id)
    entrega_actual = aliased(Entrega)
    tipo_entrega_norm = func.lower(
        func.replace(
            func.replace(func.coalesce(entrega_actual.tipoEntrega, ""), "-", "_"),
            " ",
            "_",
        )
    )

    q = (
        db.query(entrega_actual, Pedido, Cliente, Produccion)
        .join(latest_entrega_sq, latest_entrega_sq.c.entrega_id == entrega_actual.idEntrega)
        .join(Pedido, Pedido.idPedido == entrega_actual.pedidoID)
        .join(Cliente, Cliente.idCliente == Pedido.clienteID)
        .outerjoin(Produccion, Produccion.idProduccion == entrega_actual.produccionID)
        .filter(
            entrega_actual.empresaID == int(empresa_id),
            entrega_actual.domiciliarioID == int(domiciliario_id),
            func.coalesce(
                entrega_actual.reprogramadaPara,
                entrega_actual.fechaEntregaProgramada,
                entrega_actual.fechaEntrega,
            ).between(start, end),
            entrega_actual.estadoEntregaID.in_(
                [
                    domicilio_service.resolve_estado_entrega_id(db, ESTADO_ASIGNADO),
                    domicilio_service.resolve_estado_entrega_id(db, ESTADO_EN_RUTA),
                ]
            ),
            tipo_entrega_norm.notin_(domicilio_service.STORE_PICKUP_TIPO_ENTREGA_VALUES),
        )
        .order_by(
            func.coalesce(
                entrega_actual.reprogramadaPara,
                entrega_actual.fechaEntregaProgramada,
                entrega_actual.fechaEntrega,
            ).asc()
        )
    )

    if sucursal_id is not None:
        q = q.filter(func.coalesce(entrega_actual.sucursalID, Pedido.sucursalID) == int(sucursal_id))

    return q


def _build_pedidos_disponibles_query(
    db: Session,
    empresa_id: int,
    sucursal_id: int | None,
    domiciliario_id: int,
    fecha: date,
):
    start = datetime.combine(fecha, datetime.min.time())
    end = datetime.combine(fecha, datetime.max.time())
    estado_para_entrega = produccion_service.estado_produccion_id(db, produccion_service.ESTADO_PARA_ENTREGA)
    latest_entrega_sq = _latest_entrega_id_subquery(db, empresa_id)
    entrega_actual = aliased(Entrega)
    tipo_entrega_norm = func.lower(
        func.replace(
            func.replace(func.coalesce(entrega_actual.tipoEntrega, ""), "-", "_"),
            " ",
            "_",
        )
    )
    estado_pendiente_id = domicilio_service.resolve_estado_entrega_id(db, ESTADO_PENDIENTE)
    estado_no_entregado_id = domicilio_service.resolve_estado_entrega_id(db, ESTADO_NO_ENTREGADO)

    q = (
        db.query(entrega_actual, Pedido, Cliente, Produccion)
        .join(latest_entrega_sq, latest_entrega_sq.c.entrega_id == entrega_actual.idEntrega)
        .join(Pedido, Pedido.idPedido == entrega_actual.pedidoID)
        .join(Cliente, Cliente.idCliente == Pedido.clienteID)
        .join(Produccion, Produccion.idProduccion == entrega_actual.produccionID)
        .filter(
            entrega_actual.empresaID == int(empresa_id),
            func.coalesce(
                entrega_actual.reprogramadaPara,
                entrega_actual.fechaEntregaProgramada,
                entrega_actual.fechaEntrega,
            ).between(start, end),
            entrega_actual.estadoEntregaID.in_([estado_pendiente_id, estado_no_entregado_id]),
            Produccion.estado == estado_para_entrega,
            or_(
                entrega_actual.estadoEntregaID == estado_no_entregado_id,
                entrega_actual.domiciliarioID == None,
                entrega_actual.domiciliarioID == int(domiciliario_id),
            ),
            tipo_entrega_norm.notin_(domicilio_service.STORE_PICKUP_TIPO_ENTREGA_VALUES),
        )
    )

    if sucursal_id is not None:
        q = q.filter(func.coalesce(entrega_actual.sucursalID, Pedido.sucursalID) == int(sucursal_id))

    return q.order_by(
        func.coalesce(
            entrega_actual.reprogramadaPara,
            entrega_actual.fechaEntregaProgramada,
            entrega_actual.fechaEntrega,
        ).asc()
    )


@router.get("/domiciliarios", response_model=DomiciliarioListResponse)
def listar_domiciliarios(
    empresa_id: int = Query(..., alias="empresaID"),
    sucursal_id: int | None = Query(None, alias="sucursalID"),
    solo_activos: bool = Query(True, alias="soloActivos"),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)
    q = db.query(Domiciliario).filter(Domiciliario.empresaID == int(empresa_id))
    q = q.filter(func.upper(Domiciliario.cargo) == "DOMICILIARIO")
    if sucursal_id is not None:
        q = q.filter(Domiciliario.sucursalID == int(sucursal_id))
    if solo_activos:
        q = q.filter(_activo_truthy(Domiciliario.activo))

    rows = q.order_by(Domiciliario.nombre.asc()).all()
    return DomiciliarioListResponse(
        items=[
            DomiciliarioItem(
                idDomiciliario=int(row.idDomiciliario),
                usuarioID=(int(row.usuarioID) if getattr(row, "usuarioID", None) is not None else None),
                nombre=str(row.nombre or ""),
                telefono=None,
                activo=bool(row.activo),
            )
            for row in rows
        ]
    )


@router.get("", response_model=DomicilioAdminListResponse)
def listar_admin(
    empresa_id: int = Query(..., alias="empresaID"),
    sucursal_id: int | None = Query(None, alias="sucursalID"),
    filtro: str = Query("hoy"),
    fecha: date = Query(default_factory=date.today),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)
    latest_entrega_sq = _latest_entrega_id_subquery(db, empresa_id)
    entrega_actual = aliased(Entrega)

    q = (
        db.query(entrega_actual, Pedido, Cliente, Produccion, Domiciliario)
        .join(latest_entrega_sq, latest_entrega_sq.c.entrega_id == entrega_actual.idEntrega)
        .join(Pedido, Pedido.idPedido == entrega_actual.pedidoID)
        .join(Cliente, Cliente.idCliente == Pedido.clienteID)
        .outerjoin(Produccion, Produccion.idProduccion == entrega_actual.produccionID)
        .outerjoin(Domiciliario, Domiciliario.idDomiciliario == entrega_actual.domiciliarioID)
        .filter(entrega_actual.empresaID == int(empresa_id))
    )

    if sucursal_id is not None:
        q = q.filter(func.coalesce(entrega_actual.sucursalID, Pedido.sucursalID) == int(sucursal_id))

    estado_filtro = domicilio_service.estado_from_filtro(filtro)
    if estado_filtro:
        q = q.filter(
            entrega_actual.estadoEntregaID == domicilio_service.resolve_estado_entrega_id(db, estado_filtro)
        )

    rango = domicilio_service.filtro_rango_fecha(filtro, fecha)
    if rango:
        start, end = rango
        q = q.filter(
            func.coalesce(
                entrega_actual.reprogramadaPara,
                entrega_actual.fechaEntregaProgramada,
                entrega_actual.fechaEntrega,
            ).between(start, end)
        )

    rows = q.order_by(
        func.coalesce(
            entrega_actual.reprogramadaPara,
            entrega_actual.fechaEntregaProgramada,
            entrega_actual.fechaEntrega,
        ).asc()
    ).all()

    items: list[DomicilioAdminItem] = []
    for entrega, pedido, cliente, produccion, domiciliario in rows:
        estado = domicilio_service.estado_norm(entrega.estadoEntregaID)
        lat_destino, lng_destino = domicilio_service.payload_destino_lat_lng(entrega)
        lat, lng = domicilio_service.payload_lat_lng(entrega)
        items.append(
            DomicilioAdminItem(
                idEntrega=int(entrega.idEntrega),
                produccionID=(int(entrega.produccionID) if entrega.produccionID else None),
                pedidoID=int(pedido.idPedido),
                numeroPedido=_numero_pedido_valor(pedido),
                codigoPedido=(str(pedido.codigoPedido) if pedido.codigoPedido else None),
                cliente=str(cliente.nombreCompleto or "Cliente"),
                destinatario=str(entrega.destinatario or "") or None,
                telefonoDestino=str(entrega.telefonoDestino or "") or None,
                direccion=str(entrega.direccion or "") or None,
                barrio=str(entrega.barrioNombre or "") or None,
                observacion=(str(entrega.observacionGeneral or entrega.observaciones or "").strip() or None),
                horaEntrega=str(entrega.rangoHora or "") or None,
                fechaEntregaProgramada=(entrega.reprogramadaPara or entrega.fechaEntregaProgramada or entrega.fechaEntrega),
                domiciliarioID=(int(entrega.domiciliarioID) if entrega.domiciliarioID else None),
                domiciliario=(str(domiciliario.nombre or "") if domiciliario else None),
                estado=estado,
                intentoNumero=max(int(entrega.intentoNumero or 1), 1),
                tiempoRestanteHoras=domicilio_service.tiempo_restante_horas(entrega),
                prioridad=(str(produccion.prioridad or "") if produccion and produccion.prioridad else None),
                latitudDestino=lat_destino,
                longitudDestino=lng_destino,
                latitudEntrega=lat,
                longitudEntrega=lng,
            )
        )

    items = sort_operativo(
        items,
        due_at=lambda item: item.fechaEntregaProgramada,
        priority=lambda item: item.prioridad,
    )
    return DomicilioAdminListResponse(items=items, total=len(items))


@router.put(
    "/{entrega_id}/asignar",
    response_model=DomicilioActionResponse,
    dependencies=[Depends(require_module_access("domicilios", "puedeEditar"))],
)
def asignar_domiciliario(
    entrega_id: int,
    payload: AsignarDomiciliarioRequest,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    entrega = _locked_current_entrega(db, int(auth.empresaID), entrega_id)
    assert_same_empresa(auth, int(entrega.empresaID))

    estado_actual = domicilio_service.estado_norm(entrega.estadoEntregaID)
    if payload.domiciliarioID is None:
        domicilio_service.assert_transition_allowed_for_empresa(
            db=db,
            empresa_id=int(entrega.empresaID),
            current=estado_actual,
            target=ESTADO_PENDIENTE,
        )
        entrega.domiciliarioID = None
        entrega.fechaAsignacion = None
        entrega.estadoEntregaID = domicilio_service.resolve_estado_entrega_id(db, ESTADO_PENDIENTE)
    else:
        if domicilio_service.is_store_pickup_tipo_entrega(entrega.tipoEntrega):
            raise _err(
                "DOMICILIO_STORE_PICKUP_ASSIGNMENT_NOT_ALLOWED",
                "Los pedidos para recoger en tienda no permiten asignar domiciliario",
                status_code=400,
            )

        domiciliario = db.query(Domiciliario).filter(Domiciliario.idDomiciliario == payload.domiciliarioID).first()
        if not domiciliario or int(domiciliario.empresaID) != int(entrega.empresaID):
            raise _err("DOMICILIO_DOMICILIARIO_INVALID", "Domiciliario inválido para la empresa", status_code=400)

        if entrega.sucursalID and int(domiciliario.sucursalID) != int(entrega.sucursalID):
            raise _err("DOMICILIO_SCOPE_INVALID", "Domiciliario no pertenece a la sucursal de la entrega", status_code=400)

        domicilio_service.assert_domiciliario_capacity(
            db=db,
            empresa_id=int(entrega.empresaID),
            sucursal_id=(int(entrega.sucursalID) if entrega.sucursalID is not None else None),
            domiciliario_id=int(domiciliario.idDomiciliario),
            ignore_entrega_id=int(entrega.idEntrega),
        )
        domicilio_service.assert_transition_allowed_for_empresa(
            db=db,
            empresa_id=int(entrega.empresaID),
            current=estado_actual,
            target=ESTADO_ASIGNADO,
        )

        entrega.domiciliarioID = int(domiciliario.idDomiciliario)
        entrega.fechaAsignacion = datetime.now(timezone.utc)
        entrega.estadoEntregaID = domicilio_service.resolve_estado_entrega_id(db, ESTADO_ASIGNADO)

    entrega.updatedAt = datetime.now(timezone.utc)
    db.commit()

    return DomicilioActionResponse(
        status="ok",
        idEntrega=int(entrega.idEntrega),
        estado=domicilio_service.estado_norm(entrega.estadoEntregaID),
    )


@router.put(
    "/{entrega_id}/tomar",
    response_model=DomicilioActionResponse,
    dependencies=[Depends(require_module_access("domicilios", "puedeEditar"))],
)
def tomar_entrega(
    entrega_id: int,
    payload: TomarEntregaRequest,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    domiciliario_id = _assert_auth_domiciliario(db, auth)
    entrega = _locked_current_entrega(db, int(auth.empresaID), entrega_id)
    assert_same_empresa(auth, int(entrega.empresaID))

    if domicilio_service.is_store_pickup_tipo_entrega(entrega.tipoEntrega):
        raise _err(
            "DOMICILIO_STORE_PICKUP_TAKE_NOT_ALLOWED",
            "Los pedidos para recoger en tienda no permiten asignar domiciliario",
            status_code=400,
        )

    actual = domicilio_service.estado_norm(entrega.estadoEntregaID)
    if actual not in {ESTADO_PENDIENTE, ESTADO_NO_ENTREGADO}:
        raise _err("DOMICILIO_TRANSITION_INVALID", f"No se puede tomar entrega desde estado {actual}", status_code=400)

    domicilio_service.assert_domiciliario_capacity(
        db=db,
        empresa_id=int(auth.empresaID),
        sucursal_id=(int(entrega.sucursalID) if entrega.sucursalID is not None else None),
        domiciliario_id=domiciliario_id,
    )

    if actual == ESTADO_PENDIENTE:
        domicilio_service.assert_transition_allowed_for_empresa(
            db=db,
            empresa_id=int(entrega.empresaID),
            current=actual,
            target=ESTADO_ASIGNADO,
        )
        updated_rows = (
            db.query(Entrega)
            .filter(
                Entrega.idEntrega == int(entrega.idEntrega),
                Entrega.empresaID == int(entrega.empresaID),
                Entrega.domiciliarioID == None,
                Entrega.estadoEntregaID == domicilio_service.resolve_estado_entrega_id(db, ESTADO_PENDIENTE),
            )
            .update(
                {
                    Entrega.domiciliarioID: int(domiciliario_id),
                    Entrega.fechaAsignacion: datetime.now(timezone.utc),
                    Entrega.updatedAt: datetime.now(timezone.utc),
                    Entrega.estadoEntregaID: domicilio_service.resolve_estado_entrega_id(db, ESTADO_ASIGNADO),
                },
                synchronize_session=False,
            )
        )
        if updated_rows != 1:
            db.rollback()
            raise _err(
                "DOMICILIO_ALREADY_ASSIGNED",
                "La entrega ya fue tomada por otro domiciliario",
                status_code=409,
            )
        db.commit()
        return DomicilioActionResponse(status="ok", idEntrega=int(entrega.idEntrega), estado=ESTADO_ASIGNADO)

    domicilio_service.assert_transition_allowed_for_empresa(
        db=db,
        empresa_id=int(entrega.empresaID),
        current=actual,
        target=ESTADO_ASIGNADO,
    )

    next_entrega = domicilio_service.create_retry_entrega(
        db=db,
        previous=entrega,
        domiciliario_id=domiciliario_id,
        next_state=ESTADO_ASIGNADO,
    )
    db.commit()
    return DomicilioActionResponse(status="ok", idEntrega=int(next_entrega.idEntrega), estado=ESTADO_ASIGNADO)


@router.put(
    "/{entrega_id}/en-ruta",
    response_model=DomicilioActionResponse,
    dependencies=[Depends(require_module_access("domicilios", "puedeEditar"))],
)
def marcar_en_ruta(
    entrega_id: int,
    payload: MarcarEnRutaRequest,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    entrega = _locked_current_entrega(db, int(auth.empresaID), entrega_id)
    assert_same_empresa(auth, int(entrega.empresaID))
    _assert_entrega_actor_scope(entrega, auth, db)

    actual = domicilio_service.estado_norm(entrega.estadoEntregaID)
    domicilio_service.assert_transition_allowed_for_empresa(
        db=db,
        empresa_id=int(entrega.empresaID),
        current=actual,
        target=ESTADO_EN_RUTA,
    )

    if not entrega.domiciliarioID:
        raise _err("DOMICILIO_DOMICILIARIO_REQUIRED", "Debes asignar un domiciliario antes de salir a ruta", status_code=400)

    entrega.estadoEntregaID = domicilio_service.resolve_estado_entrega_id(db, ESTADO_EN_RUTA)
    entrega.fechaSalida = datetime.now(timezone.utc)
    entrega.updatedAt = datetime.now(timezone.utc)
    db.commit()

    return DomicilioActionResponse(status="ok", idEntrega=int(entrega.idEntrega), estado=ESTADO_EN_RUTA)


@router.put(
    "/{entrega_id}/entregado",
    response_model=DomicilioActionResponse,
    dependencies=[Depends(require_module_access("domicilios", "puedeEditar"))],
)
def marcar_entregado(
    entrega_id: int,
    usuarioCambio: str = Form(...),
    firmaNombre: str = Form(...),
    firmaDocumento: str = Form(...),
    firmaImagenUrl: str | None = Form(None),
    evidenciaFotoUrl: str | None = Form(None),
    latitudEntrega: float = Form(...),
    longitudEntrega: float = Form(...),
    observaciones: str | None = Form(None),
    firmaImagen: UploadFile | None = File(None),
    evidenciaFoto: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    entrega = _locked_current_entrega(db, int(auth.empresaID), entrega_id)
    assert_same_empresa(auth, int(entrega.empresaID))
    _assert_entrega_actor_scope(entrega, auth, db)

    actual = domicilio_service.estado_norm(entrega.estadoEntregaID)
    domicilio_service.assert_transition_allowed_for_empresa(
        db=db,
        empresa_id=int(entrega.empresaID),
        current=actual,
        target=ESTADO_ENTREGADO,
    )

    entrega.estadoEntregaID = domicilio_service.resolve_estado_entrega_id(db, ESTADO_ENTREGADO)
    entrega.fechaEntrega = datetime.now(timezone.utc)
    entrega.firmaNombre = firmaNombre.strip()
    entrega.firmaDocumento = firmaDocumento.strip()
    if firmaImagen is not None:
        entrega.firmaImagenUrl = _save_upload_file(firmaImagen)
    elif firmaImagenUrl:
        entrega.firmaImagenUrl = firmaImagenUrl.strip()
    entrega.evidenciaFotoUrl = _save_upload_file(evidenciaFoto) or (evidenciaFotoUrl.strip() if evidenciaFotoUrl else None)
    entrega.latitudEntrega = latitudEntrega
    entrega.longitudEntrega = longitudEntrega
    entrega.observaciones = (observaciones or "").strip() or entrega.observaciones
    entrega.updatedAt = datetime.now(timezone.utc)
    db.commit()

    return DomicilioActionResponse(status="ok", idEntrega=int(entrega.idEntrega), estado=ESTADO_ENTREGADO)


@router.put(
    "/{entrega_id}/no-entregado",
    response_model=DomicilioActionResponse,
    dependencies=[Depends(require_module_access("domicilios", "puedeEditar"))],
)
def marcar_no_entregado(
    entrega_id: int,
    payload: MarcarNoEntregadoRequest,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    entrega = _locked_current_entrega(db, int(auth.empresaID), entrega_id)
    assert_same_empresa(auth, int(entrega.empresaID))
    _assert_entrega_actor_scope(entrega, auth, db)

    actual = domicilio_service.estado_norm(entrega.estadoEntregaID)
    domicilio_service.assert_transition_allowed_for_empresa(
        db=db,
        empresa_id=int(entrega.empresaID),
        current=actual,
        target=ESTADO_NO_ENTREGADO,
    )

    entrega.estadoEntregaID = domicilio_service.resolve_estado_entrega_id(db, ESTADO_NO_ENTREGADO)
    entrega.motivoNoEntregado = payload.motivo.strip()
    entrega.observaciones = (payload.observaciones or "").strip() or entrega.observaciones
    entrega.reprogramadaPara = payload.reprogramarPara
    entrega.updatedAt = datetime.now(timezone.utc)
    db.commit()

    return DomicilioActionResponse(status="ok", idEntrega=int(entrega.idEntrega), estado=ESTADO_NO_ENTREGADO)


@router.get("/mis-entregas", response_model=DomicilioCourierListResponse)
def listar_mis_entregas(
    empresa_id: int = Query(..., alias="empresaID"),
    sucursal_id: int | None = Query(None, alias="sucursalID"),
    domiciliario_id: int = Query(..., alias="domiciliarioID"),
    fecha: date = Query(default_factory=date.today),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)

    rows = _build_mis_entregas_query(db, empresa_id, sucursal_id, domiciliario_id, fecha).all()
    items = [_build_courier_card(entrega, pedido, cliente, produccion) for entrega, pedido, cliente, produccion in rows]
    items = sort_operativo(
        items,
        due_at=lambda item: item.fechaEntregaProgramada,
        priority=lambda item: item.prioridad,
    )
    return DomicilioCourierListResponse(items=items, total=len(items))


@router.get("/mis-pedidos", response_model=DomicilioCourierListResponse)
def listar_mis_pedidos(
    empresa_id: int = Query(..., alias="empresaID"),
    sucursal_id: int | None = Query(None, alias="sucursalID"),
    fecha: date = Query(default_factory=date.today),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)
    domiciliario_id = _assert_auth_domiciliario(db, auth)

    rows = _build_mis_entregas_query(db, empresa_id, sucursal_id, domiciliario_id, fecha).all()
    items = [_build_courier_card(entrega, pedido, cliente, produccion) for entrega, pedido, cliente, produccion in rows]
    items = sort_operativo(
        items,
        due_at=lambda item: item.fechaEntregaProgramada,
        priority=lambda item: item.prioridad,
    )
    return DomicilioCourierListResponse(items=items, total=len(items))


@router.get("/pedidos-disponibles", response_model=DomicilioCourierListResponse)
def listar_pedidos_disponibles(
    empresa_id: int = Query(..., alias="empresaID"),
    sucursal_id: int | None = Query(None, alias="sucursalID"),
    fecha: date = Query(default_factory=date.today),
    latitud: float | None = Query(None),
    longitud: float | None = Query(None),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)
    domiciliario_id = _assert_auth_domiciliario(db, auth)

    rows = _build_pedidos_disponibles_query(db, empresa_id, sucursal_id, domiciliario_id, fecha).all()

    items: list[DomicilioCourierCard] = []
    for entrega, pedido, cliente, produccion in rows:
        lat_destino, lng_destino = domicilio_service.payload_destino_lat_lng(entrega)
        items.append(
            _build_courier_card(
                entrega,
                pedido,
                cliente,
                produccion,
                distancia_km=domicilio_service.haversine_distance_km(latitud, longitud, lat_destino, lng_destino),
            )
        )

    if latitud is not None and longitud is not None:
        items.sort(
            key=lambda item: (
                item.distanciaKm if item.distanciaKm is not None else float("inf"),
                item.fechaEntregaProgramada or datetime.max,
            )
        )
    else:
        items = sort_operativo(
            items,
            due_at=lambda item: item.fechaEntregaProgramada,
            priority=lambda item: item.prioridad,
        )

    return DomicilioCourierListResponse(items=items, total=len(items))


@router.get("/mis-entregas/propias", response_model=DomicilioCourierListResponse)
def listar_mis_entregas_propias(
    empresa_id: int = Query(..., alias="empresaID"),
    sucursal_id: int | None = Query(None, alias="sucursalID"),
    fecha: date = Query(default_factory=date.today),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)
    domiciliario_id = _assert_auth_domiciliario(db, auth)

    rows = _build_mis_entregas_query(db, empresa_id, sucursal_id, domiciliario_id, fecha).all()
    items = [_build_courier_card(entrega, pedido, cliente, produccion) for entrega, pedido, cliente, produccion in rows]
    items = sort_operativo(
        items,
        due_at=lambda item: item.fechaEntregaProgramada,
        priority=lambda item: item.prioridad,
    )
    return DomicilioCourierListResponse(items=items, total=len(items))
