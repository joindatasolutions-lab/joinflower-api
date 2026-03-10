from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import assert_same_empresa, get_current_auth_context, require_module_access
from app.database import get_db
from app.models.cliente import Cliente
from app.models.domiciliario import Domiciliario
from app.models.entrega import Entrega
from app.models.pedido import Pedido
from app.models.produccion import Produccion
from app.services import domicilio_service
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
    MarcarEntregadoRequest,
    MarcarNoEntregadoRequest,
)

router = APIRouter(
    prefix="/domicilios",
    tags=["Domicilios"],
    dependencies=[Depends(require_module_access("domicilios", "puedeVer"))],
)


def _numero_pedido_valor(pedido: Pedido) -> int:
    if pedido.numeroPedido is not None:
        return int(pedido.numeroPedido)
    return int(pedido.idPedido)


@router.get("/domiciliarios", response_model=DomiciliarioListResponse)
def listar_domiciliarios(
    empresa_id: int = Query(..., alias="empresaID"),
    sucursal_id: int | None = Query(None, alias="sucursalID"),
    solo_activos: bool = Query(True, alias="soloActivos"),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)
    q = db.query(Domiciliario).filter(Domiciliario.empresaID == empresa_id)
    if sucursal_id is not None:
        q = q.filter(Domiciliario.sucursalID == sucursal_id)
    if solo_activos:
        q = q.filter(Domiciliario.activo == True)

    rows = q.order_by(Domiciliario.nombre.asc()).all()
    return DomiciliarioListResponse(
        items=[
            DomiciliarioItem(
                idDomiciliario=int(row.idDomiciliario),
                nombre=str(row.nombre or ""),
                telefono=str(row.telefono or "") or None,
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

    q = (
        db.query(Entrega, Pedido, Cliente, Produccion, Domiciliario)
        .join(Pedido, Pedido.idPedido == Entrega.pedidoID)
        .join(Cliente, Cliente.idCliente == Pedido.clienteID)
        .outerjoin(Produccion, Produccion.idProduccion == Entrega.produccionID)
        .outerjoin(Domiciliario, Domiciliario.idDomiciliario == Entrega.domiciliarioID)
        .filter(Entrega.empresaID == empresa_id)
    )

    if sucursal_id is not None:
        q = q.filter(func.coalesce(Entrega.sucursalID, Pedido.sucursalID) == sucursal_id)

    estado_filtro = domicilio_service.estado_from_filtro(filtro)
    if estado_filtro:
        q = q.filter(func.upper(Entrega.estado) == estado_filtro.upper())

    rango = domicilio_service.filtro_rango_fecha(filtro, fecha)
    if rango:
        start, end = rango
        q = q.filter(func.coalesce(Entrega.reprogramadaPara, Entrega.fechaEntregaProgramada, Entrega.fechaEntrega).between(start, end))

    rows = q.order_by(func.coalesce(Entrega.reprogramadaPara, Entrega.fechaEntregaProgramada, Entrega.fechaEntrega).asc()).all()

    items: list[DomicilioAdminItem] = []
    for entrega, pedido, cliente, produccion, domiciliario in rows:
        estado = domicilio_service.estado_norm(entrega.estado)
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
                horaEntrega=str(entrega.rangoHora or "") or None,
                fechaEntregaProgramada=(entrega.reprogramadaPara or entrega.fechaEntregaProgramada or entrega.fechaEntrega),
                domiciliarioID=(int(entrega.domiciliarioID) if entrega.domiciliarioID else None),
                domiciliario=(str(domiciliario.nombre or "") if domiciliario else None),
                estado=estado,
                intentoNumero=max(int(entrega.intentoNumero or 1), 1),
                tiempoRestanteHoras=domicilio_service.tiempo_restante_horas(entrega),
                prioridad=(str(produccion.prioridad or "") if produccion else None),
                latitudEntrega=lat,
                longitudEntrega=lng,
            )
        )

    return DomicilioAdminListResponse(items=items, total=len(items))


@router.put("/{entrega_id}/asignar", response_model=DomicilioActionResponse, dependencies=[Depends(require_module_access("domicilios", "puedeEditar"))])
def asignar_domiciliario(
    entrega_id: int,
    payload: AsignarDomiciliarioRequest,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    entrega = db.query(Entrega).filter(Entrega.idEntrega == entrega_id).first()
    if not entrega:
        raise HTTPException(status_code=404, detail="Entrega no encontrada")
    assert_same_empresa(auth, int(entrega.empresaID))

    estado_actual = domicilio_service.estado_norm(entrega.estado)
    if payload.domiciliarioID is None:
        entrega.domiciliarioID = None
        entrega.estado = ESTADO_PENDIENTE
    else:
        domiciliario = db.query(Domiciliario).filter(Domiciliario.idDomiciliario == payload.domiciliarioID).first()
        if not domiciliario or int(domiciliario.empresaID) != int(entrega.empresaID):
            raise HTTPException(status_code=400, detail="Domiciliario invalido para la empresa")

        if entrega.sucursalID and int(domiciliario.sucursalID) != int(entrega.sucursalID):
            raise HTTPException(status_code=400, detail="Domiciliario no pertenece a la sucursal de la entrega")

        nuevo_estado = ESTADO_ASIGNADO
        if estado_actual not in {ESTADO_PENDIENTE, ESTADO_ASIGNADO, ESTADO_NO_ENTREGADO}:
            raise HTTPException(status_code=400, detail=f"No se puede asignar desde estado {estado_actual}")

        entrega.domiciliarioID = int(domiciliario.idDomiciliario)
        entrega.fechaAsignacion = datetime.now(timezone.utc)
        entrega.estado = nuevo_estado

    entrega.updatedAt = datetime.now(timezone.utc)
    db.commit()

    return DomicilioActionResponse(status="ok", idEntrega=int(entrega.idEntrega), estado=domicilio_service.estado_norm(entrega.estado))


@router.put("/{entrega_id}/en-ruta", response_model=DomicilioActionResponse, dependencies=[Depends(require_module_access("domicilios", "puedeEditar"))])
def marcar_en_ruta(
    entrega_id: int,
    payload: MarcarEnRutaRequest,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    entrega = db.query(Entrega).filter(Entrega.idEntrega == entrega_id).first()
    if not entrega:
        raise HTTPException(status_code=404, detail="Entrega no encontrada")
    assert_same_empresa(auth, int(entrega.empresaID))

    actual = domicilio_service.estado_norm(entrega.estado)
    domicilio_service.assert_transition_allowed(actual, ESTADO_EN_RUTA)

    if not entrega.domiciliarioID:
        raise HTTPException(status_code=400, detail="Debes asignar un domiciliario antes de salir a ruta")

    entrega.estado = ESTADO_EN_RUTA
    entrega.fechaSalida = datetime.now(timezone.utc)
    entrega.updatedAt = datetime.now(timezone.utc)
    db.commit()

    return DomicilioActionResponse(status="ok", idEntrega=int(entrega.idEntrega), estado=ESTADO_EN_RUTA)


@router.put("/{entrega_id}/entregado", response_model=DomicilioActionResponse, dependencies=[Depends(require_module_access("domicilios", "puedeEditar"))])
def marcar_entregado(
    entrega_id: int,
    payload: MarcarEntregadoRequest,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    entrega = db.query(Entrega).filter(Entrega.idEntrega == entrega_id).first()
    if not entrega:
        raise HTTPException(status_code=404, detail="Entrega no encontrada")
    assert_same_empresa(auth, int(entrega.empresaID))

    actual = domicilio_service.estado_norm(entrega.estado)
    domicilio_service.assert_transition_allowed(actual, ESTADO_ENTREGADO)

    entrega.estado = ESTADO_ENTREGADO
    entrega.fechaEntrega = datetime.now(timezone.utc)
    entrega.firmaNombre = payload.firmaNombre.strip()
    entrega.firmaDocumento = payload.firmaDocumento.strip()
    entrega.firmaImagenUrl = payload.firmaImagenUrl.strip()
    entrega.evidenciaFotoUrl = (payload.evidenciaFotoUrl.strip() if payload.evidenciaFotoUrl else None)
    entrega.latitudEntrega = payload.latitudEntrega
    entrega.longitudEntrega = payload.longitudEntrega
    entrega.observaciones = (payload.observaciones or "").strip() or entrega.observaciones
    entrega.updatedAt = datetime.now(timezone.utc)
    db.commit()

    return DomicilioActionResponse(status="ok", idEntrega=int(entrega.idEntrega), estado=ESTADO_ENTREGADO)


@router.put("/{entrega_id}/no-entregado", response_model=DomicilioActionResponse, dependencies=[Depends(require_module_access("domicilios", "puedeEditar"))])
def marcar_no_entregado(
    entrega_id: int,
    payload: MarcarNoEntregadoRequest,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    entrega = db.query(Entrega).filter(Entrega.idEntrega == entrega_id).first()
    if not entrega:
        raise HTTPException(status_code=404, detail="Entrega no encontrada")
    assert_same_empresa(auth, int(entrega.empresaID))

    actual = domicilio_service.estado_norm(entrega.estado)
    domicilio_service.assert_transition_allowed(actual, ESTADO_NO_ENTREGADO)

    entrega.estado = ESTADO_NO_ENTREGADO
    entrega.motivoNoEntregado = payload.motivo.strip()
    entrega.observaciones = (payload.observaciones or "").strip() or entrega.observaciones
    entrega.intentoNumero = max(int(entrega.intentoNumero or 1), 1) + 1
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

    start = datetime.combine(fecha, datetime.min.time())
    end = datetime.combine(fecha, datetime.max.time())

    q = (
        db.query(Entrega, Pedido)
        .join(Pedido, Pedido.idPedido == Entrega.pedidoID)
        .filter(
            Entrega.empresaID == empresa_id,
            Entrega.domiciliarioID == domiciliario_id,
            func.coalesce(Entrega.reprogramadaPara, Entrega.fechaEntregaProgramada, Entrega.fechaEntrega).between(start, end),
            func.upper(Entrega.estado).in_([ESTADO_ASIGNADO.upper(), ESTADO_EN_RUTA.upper(), ESTADO_NO_ENTREGADO.upper()]),
        )
        .order_by(func.coalesce(Entrega.reprogramadaPara, Entrega.fechaEntregaProgramada, Entrega.fechaEntrega).asc())
    )

    if sucursal_id is not None:
        q = q.filter(Entrega.sucursalID == sucursal_id)

    rows = q.all()

    items: list[DomicilioCourierCard] = []
    for entrega, pedido in rows:
        items.append(
            DomicilioCourierCard(
                idEntrega=int(entrega.idEntrega),
                pedidoID=int(entrega.pedidoID),
                numeroPedido=_numero_pedido_valor(pedido),
                codigoPedido=(str(pedido.codigoPedido) if pedido.codigoPedido else None),
                destinatario=str(entrega.destinatario or "") or None,
                direccion=str(entrega.direccion or "") or None,
                barrio=str(entrega.barrioNombre or "") or None,
                telefonoDestino=str(entrega.telefonoDestino or "") or None,
                mensaje=str(entrega.mensaje or "") or None,
                estado=domicilio_service.estado_norm(entrega.estado),
                horaEntrega=str(entrega.rangoHora or "") or None,
                fechaEntregaProgramada=(entrega.reprogramadaPara or entrega.fechaEntregaProgramada or entrega.fechaEntrega),
            )
        )

    return DomicilioCourierListResponse(items=items, total=len(items))
