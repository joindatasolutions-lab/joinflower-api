from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4
import os
import shutil

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import String, and_, cast, func, or_, text
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
from app.core.timezone import colombia_today
from app.database import get_db
from app.models.barrio import Barrio
from app.models.cliente import Cliente
from app.models.domiciliario import Domiciliario
from app.models.entrega import Entrega
from app.models.pedido import Pedido
from app.models.pedidodetalle import PedidoDetalle
from app.models.producto import Producto
from app.models.produccion import Produccion
from app.models.zona import Zona
from app.schemas.domicilios import (
    AsignarDomiciliarioRequest,
    DomicilioDetailResponse,
    DomiciliarioItem,
    DomiciliarioListResponse,
    DomicilioActionResponse,
    DomicilioAdminItem,
    DomicilioAdminListResponse,
    DomicilioContadoresResponse,
    DomicilioCourierCard,
    DomicilioCourierListResponse,
    PedidoAsignadoResponse,
    PedidoDisponibleItem,
    ESTADO_ASIGNADO,
    ESTADO_EN_RUTA,
    ESTADO_ENTREGADO,
    ESTADO_NO_ENTREGADO,
    ESTADO_PENDIENTE,
    MarcarEnRutaRequest,
    MarcarNoEntregadoRequest,
    OrderItemDetail,
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


def _assert_role_domiciliario(auth):
    rol = str(getattr(auth, "rol", "") or "").strip().lower().replace(" ", "_")
    if rol != "domiciliario":
        raise _err(
            "DOMICILIO_ROLE_REQUIRED",
            "Solo usuarios con rol DOMICILIARIO pueden autoasignarse pedidos",
            status_code=403,
        )


def _estado_api(entrega: Entrega) -> str:
    estado = domicilio_service.estado_norm(entrega.estadoEntregaID)
    if estado == ESTADO_PENDIENTE:
        return "SIN_ASIGNAR"
    if estado == ESTADO_ASIGNADO:
        return "ASIGNADO"
    if estado == ESTADO_EN_RUTA:
        return "EN_CAMINO"
    if estado == ESTADO_ENTREGADO:
        return "ENTREGADO"
    if estado == ESTADO_NO_ENTREGADO:
        return "NO_ENTREGADO"
    return estado.upper()


def _numero_pedido_api(pedido: Pedido) -> str:
    if pedido.codigoPedido:
        return str(pedido.codigoPedido)
    if pedido.numeroPedido is not None:
        return str(pedido.numeroPedido)
    return str(pedido.idPedido)


def _fecha_entrega_programada(entrega: Entrega) -> datetime | None:
    return entrega.reprogramadaPara or entrega.fechaEntregaProgramada or entrega.fechaEntrega


def _hora_entrega_hhmm(entrega: Entrega) -> str | None:
    fecha_programada = _fecha_entrega_programada(entrega)
    if fecha_programada:
        return fecha_programada.strftime("%H:%M")

    rango_hora = str(entrega.rangoHora or "").strip()
    match = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", rango_hora)
    if match:
        return f"{int(match.group(1)):02d}:{match.group(2)}"

    return rango_hora or None


def _location_payload(entrega: Entrega, barrio: Barrio | None = None, zona: Zona | None = None) -> dict:
    barrio_id = getattr(barrio, "idBarrio", None)
    if barrio_id is None:
        barrio_id = getattr(entrega, "barrioID", None)

    nombre_barrio = getattr(barrio, "nombreBarrio", None) or getattr(entrega, "barrioNombre", None)
    nombre_barrio = str(nombre_barrio).strip() if nombre_barrio else None

    zona_id = getattr(zona, "idZona", None)
    if zona_id is None:
        zona_id = getattr(barrio, "zonaID", None)

    nombre_zona = getattr(zona, "nombreZona", None)
    nombre_zona = str(nombre_zona).strip() if nombre_zona else None

    return {
        "barrioId": int(barrio_id) if barrio_id is not None else None,
        "nombreBarrio": nombre_barrio,
        "barrio": nombre_barrio,
        "zonaId": int(zona_id) if zona_id is not None else None,
        "nombreZona": nombre_zona,
        "zona": nombre_zona,
    }


def _with_location_joins(query, entrega_actual, pedido_model):
    barrio_by_id = and_(
        entrega_actual.barrioID != None,
        Barrio.empresaID == entrega_actual.empresaID,
        Barrio.idBarrio == entrega_actual.barrioID,
    )
    barrio_by_name = and_(
        entrega_actual.barrioID == None,
        Barrio.empresaID == entrega_actual.empresaID,
        func.lower(Barrio.nombreBarrio) == func.lower(entrega_actual.barrioNombre),
        or_(
            Barrio.sucursalID == None,
            Barrio.sucursalID == func.coalesce(entrega_actual.sucursalID, pedido_model.sucursalID),
        ),
    )
    barrio_match = or_(barrio_by_id, barrio_by_name)
    return query.outerjoin(Barrio, barrio_match).outerjoin(Zona, Zona.idZona == Barrio.zonaID)


def _unpack_delivery_row(row):
    if len(row) == 6:
        return row
    entrega, pedido, cliente, produccion = row
    return entrega, pedido, cliente, produccion, None, None


def _build_pedido_disponible_item(
    entrega: Entrega,
    pedido: Pedido,
    cliente: Cliente | None,
    produccion: Produccion | None,
    barrio: Barrio | None = None,
    zona: Zona | None = None,
) -> PedidoDisponibleItem:
    return PedidoDisponibleItem(
        id=int(pedido.idPedido),
        numeroPedido=_numero_pedido_api(pedido),
        cliente=str((cliente.nombreCompleto if cliente else None) or "Cliente"),
        direccion=(str(entrega.direccion).strip() if entrega.direccion else None),
        horaEntrega=_hora_entrega_hhmm(entrega),
        fechaEntregaProgramada=_fecha_entrega_programada(entrega),
        **_location_payload(entrega, barrio, zona),
        estado=_estado_api(entrega),
        prioridad=(str(produccion.prioridad or "") if produccion and produccion.prioridad else None),
    )


def _ensure_domicilio_auditoria_table(db: Session):
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS petalops.domicilio_auditoria (
              id_audit BIGSERIAL PRIMARY KEY,
              empresa_id BIGINT NOT NULL,
              sucursal_id BIGINT,
              pedido_id BIGINT NOT NULL,
              entrega_id BIGINT NOT NULL,
              actor_user_id BIGINT,
              actor_login VARCHAR(120) NOT NULL,
              domiciliario_id BIGINT,
              accion VARCHAR(60) NOT NULL,
              estado_anterior VARCHAR(40),
              estado_nuevo VARCHAR(40),
              detalle_json TEXT,
              created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
    )
    db.execute(text("CREATE INDEX IF NOT EXISTS idx_domicilio_auditoria_empresa_fecha ON petalops.domicilio_auditoria (empresa_id, created_at DESC);"))
    db.execute(text("CREATE INDEX IF NOT EXISTS idx_domicilio_auditoria_pedido ON petalops.domicilio_auditoria (empresa_id, pedido_id);"))


def _audit_domicilio_action(
    db: Session,
    auth,
    entrega: Entrega,
    accion: str,
    estado_anterior: str | None,
    estado_nuevo: str | None,
    extra: dict | None = None,
):
    _ensure_domicilio_auditoria_table(db)
    db.execute(
        text(
            """
            INSERT INTO petalops.domicilio_auditoria (
                empresa_id,
                sucursal_id,
                pedido_id,
                entrega_id,
                actor_user_id,
                actor_login,
                domiciliario_id,
                accion,
                estado_anterior,
                estado_nuevo,
                detalle_json,
                created_at
            )
            VALUES (
                :empresa_id,
                :sucursal_id,
                :pedido_id,
                :entrega_id,
                :actor_user_id,
                :actor_login,
                :domiciliario_id,
                :accion,
                :estado_anterior,
                :estado_nuevo,
                :detalle_json,
                CURRENT_TIMESTAMP
            )
            """
        ),
        {
            "empresa_id": int(entrega.empresaID),
            "sucursal_id": (int(entrega.sucursalID) if entrega.sucursalID is not None else None),
            "pedido_id": int(entrega.pedidoID),
            "entrega_id": int(entrega.idEntrega),
            "actor_user_id": getattr(auth, "userID", None),
            "actor_login": str(getattr(auth, "login", None) or getattr(auth, "nombre", None) or "system"),
            "domiciliario_id": (int(entrega.domiciliarioID) if entrega.domiciliarioID is not None else None),
            "accion": accion,
            "estado_anterior": estado_anterior,
            "estado_nuevo": estado_nuevo,
            "detalle_json": json.dumps(extra or {}, ensure_ascii=True),
        },
    )


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
    barrio: Barrio | None = None,
    zona: Zona | None = None,
    distancia_km: float | None = None,
) -> DomicilioCourierCard:
    lat_destino, lng_destino = domicilio_service.payload_destino_lat_lng(entrega)
    lat, lng = domicilio_service.payload_lat_lng(entrega)
    return DomicilioCourierCard(
        idEntrega=int(entrega.idEntrega),
        pedidoID=int(entrega.pedidoID),
        numeroPedido=_numero_pedido_api(pedido),
        codigoPedido=(str(pedido.codigoPedido) if pedido.codigoPedido else None),
        cliente=(str(cliente.nombreCompleto or "Cliente") if cliente else None),
        destinatario=str(entrega.destinatario or "") or None,
        direccion=str(entrega.direccion or "") or None,
        **_location_payload(entrega, barrio, zona),
        telefonoDestino=str(entrega.telefonoDestino or "") or None,
        mensaje=str(entrega.mensaje or "") or None,
        observacion=(str(entrega.observacionGeneral or entrega.observaciones or "").strip() or None),
        estado=domicilio_service.estado_norm(entrega.estadoEntregaID),
        horaEntrega=str(entrega.rangoHora or "") or None,
        fechaEntregaProgramada=_fecha_entrega_programada(entrega),
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
        db.query(entrega_actual, Pedido, Cliente, Produccion, Barrio, Zona)
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

    q = _with_location_joins(q, entrega_actual, Pedido)

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
        db.query(entrega_actual, Pedido, Cliente, Produccion, Barrio, Zona)
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

    q = _with_location_joins(q, entrega_actual, Pedido)

    if sucursal_id is not None:
        q = q.filter(func.coalesce(entrega_actual.sucursalID, Pedido.sucursalID) == int(sucursal_id))

    return q.order_by(
        func.coalesce(
            entrega_actual.reprogramadaPara,
            entrega_actual.fechaEntregaProgramada,
            entrega_actual.fechaEntrega,
        ).asc()
    )


def _build_pedidos_sin_asignar_query(
    db: Session,
    empresa_id: int,
    sucursal_id: int | None,
    fecha_desde: datetime,
    fecha_hasta: datetime,
    include_location: bool = True,
):
    estado_para_entrega = produccion_service.estado_produccion_id(db, produccion_service.ESTADO_PARA_ENTREGA)
    estado_pendiente_id = domicilio_service.resolve_estado_entrega_id(db, ESTADO_PENDIENTE)
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
        db.query(entrega_actual, Pedido, Cliente, Produccion, Barrio, Zona)
        .join(latest_entrega_sq, latest_entrega_sq.c.entrega_id == entrega_actual.idEntrega)
        .join(Pedido, Pedido.idPedido == entrega_actual.pedidoID)
        .join(Cliente, Cliente.idCliente == Pedido.clienteID)
        .join(Produccion, Produccion.idProduccion == entrega_actual.produccionID)
        .filter(
            entrega_actual.empresaID == int(empresa_id),
            entrega_actual.domiciliarioID == None,
            entrega_actual.estadoEntregaID == estado_pendiente_id,
            Produccion.estado == estado_para_entrega,
            func.coalesce(
                entrega_actual.reprogramadaPara,
                entrega_actual.fechaEntregaProgramada,
                entrega_actual.fechaEntrega,
            ).between(fecha_desde, fecha_hasta),
            tipo_entrega_norm.notin_(domicilio_service.STORE_PICKUP_TIPO_ENTREGA_VALUES),
        )
    )

    if include_location:
        q = _with_location_joins(q, entrega_actual, Pedido)

    if sucursal_id is not None:
        q = q.filter(func.coalesce(entrega_actual.sucursalID, Pedido.sucursalID) == int(sucursal_id))

    return q.order_by(
        func.coalesce(
            entrega_actual.reprogramadaPara,
            entrega_actual.fechaEntregaProgramada,
            entrega_actual.fechaEntrega,
        ).asc(),
        entrega_actual.idEntrega.asc(),
    )


def _fecha_rango(fecha: date | None, fecha_desde: date | None, fecha_hasta: date | None) -> tuple[datetime, datetime]:
    if fecha is not None:
        return datetime.combine(fecha, datetime.min.time()), datetime.combine(fecha, datetime.max.time())

    start_date = fecha_desde or colombia_today()
    end_date = fecha_hasta or start_date
    return datetime.combine(start_date, datetime.min.time()), datetime.combine(end_date, datetime.max.time())


def _domicilio_contadores(
    db: Session,
    empresa_id: int,
    sucursal_id: int | None,
    domiciliario_id: int,
    fecha_desde: datetime,
    fecha_hasta: datetime,
) -> DomicilioContadoresResponse:
    latest_entrega_sq = _latest_entrega_id_subquery(db, empresa_id)
    entrega_actual = aliased(Entrega)
    base = (
        db.query(entrega_actual)
        .join(latest_entrega_sq, latest_entrega_sq.c.entrega_id == entrega_actual.idEntrega)
        .filter(
            entrega_actual.empresaID == int(empresa_id),
            func.coalesce(
                entrega_actual.reprogramadaPara,
                entrega_actual.fechaEntregaProgramada,
                entrega_actual.fechaEntrega,
            ).between(fecha_desde, fecha_hasta),
        )
    )
    if sucursal_id is not None:
        base = base.filter(entrega_actual.sucursalID == int(sucursal_id))

    assigned_states = {
        "asignados": domicilio_service.resolve_estado_entrega_id(db, ESTADO_ASIGNADO),
        "en_camino": domicilio_service.resolve_estado_entrega_id(db, ESTADO_EN_RUTA),
        "entregados": domicilio_service.resolve_estado_entrega_id(db, ESTADO_ENTREGADO),
    }
    own_base = base.filter(entrega_actual.domiciliarioID == int(domiciliario_id))

    disponibles = _build_pedidos_sin_asignar_query(
        db=db,
        empresa_id=empresa_id,
        sucursal_id=sucursal_id,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        include_location=False,
    ).order_by(None).count()

    return DomicilioContadoresResponse(
        asignados=int(own_base.filter(entrega_actual.estadoEntregaID == assigned_states["asignados"]).count()),
        enCamino=int(own_base.filter(entrega_actual.estadoEntregaID == assigned_states["en_camino"]).count()),
        entregados=int(own_base.filter(entrega_actual.estadoEntregaID == assigned_states["entregados"]).count()),
        disponibles=int(disponibles),
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
        db.query(entrega_actual, Pedido, Cliente, Produccion, Domiciliario, Barrio, Zona)
        .join(latest_entrega_sq, latest_entrega_sq.c.entrega_id == entrega_actual.idEntrega)
        .join(Pedido, Pedido.idPedido == entrega_actual.pedidoID)
        .join(Cliente, Cliente.idCliente == Pedido.clienteID)
        .outerjoin(Produccion, Produccion.idProduccion == entrega_actual.produccionID)
        .outerjoin(Domiciliario, Domiciliario.idDomiciliario == entrega_actual.domiciliarioID)
        .filter(entrega_actual.empresaID == int(empresa_id))
    )

    q = _with_location_joins(q, entrega_actual, Pedido)

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
    for entrega, pedido, cliente, produccion, domiciliario, barrio, zona in rows:
        estado = domicilio_service.estado_norm(entrega.estadoEntregaID)
        lat_destino, lng_destino = domicilio_service.payload_destino_lat_lng(entrega)
        lat, lng = domicilio_service.payload_lat_lng(entrega)
        items.append(
            DomicilioAdminItem(
                idEntrega=int(entrega.idEntrega),
                produccionID=(int(entrega.produccionID) if entrega.produccionID else None),
                pedidoID=int(pedido.idPedido),
                numeroPedido=_numero_pedido_api(pedido),
                codigoPedido=(str(pedido.codigoPedido) if pedido.codigoPedido else None),
                cliente=str(cliente.nombreCompleto or "Cliente"),
                destinatario=str(entrega.destinatario or "") or None,
                telefonoDestino=str(entrega.telefonoDestino or "") or None,
                direccion=str(entrega.direccion or "") or None,
                **_location_payload(entrega, barrio, zona),
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
    items = [
        _build_courier_card(entrega, pedido, cliente, produccion, barrio, zona)
        for entrega, pedido, cliente, produccion, barrio, zona in (_unpack_delivery_row(row) for row in rows)
    ]
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
    items = [
        _build_courier_card(entrega, pedido, cliente, produccion, barrio, zona)
        for entrega, pedido, cliente, produccion, barrio, zona in (_unpack_delivery_row(row) for row in rows)
    ]
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
    for entrega, pedido, cliente, produccion, barrio, zona in (_unpack_delivery_row(row) for row in rows):
        lat_destino, lng_destino = domicilio_service.payload_destino_lat_lng(entrega)
        items.append(
            _build_courier_card(
                entrega,
                pedido,
                cliente,
                produccion,
                barrio,
                zona,
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


@router.get("/pedidos/disponibles", response_model=list[PedidoDisponibleItem])
def listar_pedidos_disponibles_api(
    empresa_id: int = Query(..., alias="empresaID"),
    sucursal_id: int | None = Query(None, alias="sucursalID"),
    fecha: date | None = Query(None),
    fecha_desde: date | None = Query(None, alias="fechaDesde"),
    fecha_hasta: date | None = Query(None, alias="fechaHasta"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, alias="pageSize", ge=1, le=200),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)

    start, end = _fecha_rango(fecha, fecha_desde, fecha_hasta)
    rows = (
        _build_pedidos_sin_asignar_query(
            db=db,
            empresa_id=empresa_id,
            sucursal_id=sucursal_id,
            fecha_desde=start,
            fecha_hasta=end,
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return [
        _build_pedido_disponible_item(entrega, pedido, cliente, produccion, barrio, zona)
        for entrega, pedido, cliente, produccion, barrio, zona in (_unpack_delivery_row(row) for row in rows)
    ]


@router.get("/contadores", response_model=DomicilioContadoresResponse)
def obtener_contadores_domicilio(
    empresa_id: int = Query(..., alias="empresaID"),
    sucursal_id: int | None = Query(None, alias="sucursalID"),
    fecha: date | None = Query(None),
    fecha_desde: date | None = Query(None, alias="fechaDesde"),
    fecha_hasta: date | None = Query(None, alias="fechaHasta"),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)
    _assert_role_domiciliario(auth)
    domiciliario_id = _assert_auth_domiciliario(db, auth)
    start, end = _fecha_rango(fecha, fecha_desde, fecha_hasta)
    return _domicilio_contadores(db, empresa_id, sucursal_id, domiciliario_id, start, end)


@router.post("/pedidos/{pedido_id}/asignar", response_model=PedidoAsignadoResponse)
def autoasignar_pedido(
    pedido_id: int,
    empresa_id: int = Query(..., alias="empresaID"),
    sucursal_id: int | None = Query(None, alias="sucursalID"),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)
    _assert_role_domiciliario(auth)
    domiciliario_id = _assert_auth_domiciliario(db, auth)

    pedido = (
        db.query(Pedido)
        .filter(Pedido.idPedido == int(pedido_id), Pedido.empresaID == int(empresa_id))
        .first()
    )
    if not pedido:
        raise _err("PEDIDO_NOT_FOUND", "Pedido no encontrado", status_code=404)
    if sucursal_id is not None and int(pedido.sucursalID) != int(sucursal_id):
        raise _err("DOMICILIO_SCOPE_INVALID", "Pedido no pertenece a la sucursal indicada", status_code=403)

    entrega = (
        db.query(Entrega)
        .filter(Entrega.pedidoID == int(pedido_id), Entrega.empresaID == int(empresa_id))
        .order_by(Entrega.intentoNumero.desc(), Entrega.idEntrega.desc())
        .with_for_update()
        .first()
    )
    if not entrega:
        raise _err("DOMICILIO_NOT_FOUND", "Entrega no encontrada para el pedido", status_code=404)

    if domicilio_service.is_store_pickup_tipo_entrega(entrega.tipoEntrega):
        raise _err(
            "DOMICILIO_STORE_PICKUP_TAKE_NOT_ALLOWED",
            "Los pedidos para recoger en tienda no permiten asignar domiciliario",
            status_code=400,
        )

    estado_anterior = domicilio_service.estado_norm(entrega.estadoEntregaID)
    estado_pendiente_id = domicilio_service.resolve_estado_entrega_id(db, ESTADO_PENDIENTE)
    if entrega.domiciliarioID is not None or int(entrega.estadoEntregaID) != int(estado_pendiente_id):
        raise _err(
            "DOMICILIO_ALREADY_ASSIGNED",
            "El pedido ya fue asignado a otro domiciliario.",
            status_code=409,
        )

    domicilio_service.assert_domiciliario_capacity(
        db=db,
        empresa_id=int(empresa_id),
        sucursal_id=(int(entrega.sucursalID) if entrega.sucursalID is not None else None),
        domiciliario_id=domiciliario_id,
    )
    domicilio_service.assert_transition_allowed_for_empresa(
        db=db,
        empresa_id=int(entrega.empresaID),
        current=estado_anterior,
        target=ESTADO_ASIGNADO,
    )

    assigned_at = datetime.now(timezone.utc)
    estado_asignado_id = domicilio_service.resolve_estado_entrega_id(db, ESTADO_ASIGNADO)
    updated_rows = (
        db.query(Entrega)
        .filter(
            Entrega.idEntrega == int(entrega.idEntrega),
            Entrega.empresaID == int(empresa_id),
            Entrega.pedidoID == int(pedido_id),
            Entrega.domiciliarioID == None,
            Entrega.estadoEntregaID == estado_pendiente_id,
        )
        .update(
            {
                Entrega.domiciliarioID: int(domiciliario_id),
                Entrega.fechaAsignacion: assigned_at,
                Entrega.updatedAt: assigned_at,
                Entrega.estadoEntregaID: estado_asignado_id,
            },
            synchronize_session=False,
        )
    )
    if updated_rows != 1:
        db.rollback()
        raise _err(
            "DOMICILIO_ALREADY_ASSIGNED",
            "El pedido ya fue asignado a otro domiciliario.",
            status_code=409,
        )

    entrega.domiciliarioID = int(domiciliario_id)
    entrega.fechaAsignacion = assigned_at
    entrega.updatedAt = assigned_at
    entrega.estadoEntregaID = estado_asignado_id
    _audit_domicilio_action(
        db=db,
        auth=auth,
        entrega=entrega,
        accion="AUTOASIGNACION",
        estado_anterior=estado_anterior,
        estado_nuevo=ESTADO_ASIGNADO,
        extra={"pedidoID": int(pedido_id), "usuarioTomadorID": int(auth.userID)},
    )
    db.commit()

    cliente = (
        db.query(Cliente)
        .filter(Cliente.idCliente == int(pedido.clienteID), Cliente.empresaID == int(empresa_id))
        .first()
    )
    produccion = (
        db.query(Produccion)
        .filter(
            Produccion.idProduccion == entrega.produccionID,
            Produccion.empresaID == int(empresa_id),
        )
        .first()
    )
    start, end = _fecha_rango(colombia_today(), None, None)
    base_item = _build_pedido_disponible_item(entrega, pedido, cliente, produccion)
    return PedidoAsignadoResponse(
        **base_item.model_dump(),
        idEntrega=int(entrega.idEntrega),
        domiciliarioID=int(domiciliario_id),
        fechaAsignacion=assigned_at,
        contadores=_domicilio_contadores(db, empresa_id, sucursal_id, domiciliario_id, start, end),
    )


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
    items = [
        _build_courier_card(entrega, pedido, cliente, produccion, barrio, zona)
        for entrega, pedido, cliente, produccion, barrio, zona in (_unpack_delivery_row(row) for row in rows)
    ]
    items = sort_operativo(
        items,
        due_at=lambda item: item.fechaEntregaProgramada,
        priority=lambda item: item.prioridad,
    )
    return DomicilioCourierListResponse(items=items, total=len(items))


@router.get(
    "/{entrega_id}",
    response_model=DomicilioDetailResponse,
    responses={
        200: {"description": "Detalles del pedido con items e imágenes"},
        401: {"description": "No autorizado"},
        403: {"description": "Sin permisos"},
        404: {"description": "Entrega no encontrada"},
    }
)
def obtener_detalle_domicilio(
    entrega_id: int,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    """
    GET /domicilios/:id - Devuelve detalles del pedido con items e imágenes.
    
    Requisitos:
    - Autenticación: Bearer token con acceso al módulo domicilios
    - Respuesta: JSON con items: [{ productId, name, qty, imageUrl }]
    - No devolver mensaje del cliente en listados; como customerMessage solo a usuarios autorizados
    - Errores: 200 / 401 / 403 / 404
    """
    try:
        # Obtener la entrega con validaciones de empresa
        entrega = (
            db.query(Entrega)
            .filter(
                Entrega.idEntrega == int(entrega_id),
                Entrega.empresaID == int(auth.empresaID),
            )
            .first()
        )
        
        if not entrega:
            raise HTTPException(
                status_code=404,
                detail={"code": "DOMICILIO_NOT_FOUND", "message": "Entrega no encontrada"},
            )
        
        assert_same_empresa(auth, int(entrega.empresaID))
        _assert_entrega_actor_scope(entrega, auth, db)
        
        # Obtener el pedido asociado
        pedido = (
            db.query(Pedido)
            .filter(
                Pedido.idPedido == int(entrega.pedidoID),
                Pedido.empresaID == int(entrega.empresaID),
            )
            .first()
        )
        
        if not pedido:
            raise HTTPException(
                status_code=404,
                detail={"code": "PEDIDO_NOT_FOUND", "message": "Pedido no encontrado"},
            )
        
        # Obtener cliente
        cliente = (
            db.query(Cliente)
            .filter(
                Cliente.idCliente == int(pedido.clienteID),
                Cliente.empresaID == int(pedido.empresaID),
            )
            .first()
        )
        cliente_nombre = str((cliente.nombreCompleto if cliente else None) or "Cliente")
        
        # Obtener detalles del pedido con JOIN a productos
        detalles = (
            db.query(PedidoDetalle, Producto)
            .outerjoin(
                Producto,
                (Producto.idProducto == PedidoDetalle.productoID)
                & (Producto.empresaID == PedidoDetalle.empresaID),
            )
            .filter(
                PedidoDetalle.pedidoID == int(pedido.idPedido),
                PedidoDetalle.empresaID == int(pedido.empresaID),
            )
            .order_by(PedidoDetalle.idPedidoDetalle.asc())
            .all()
        )
        
        # Construir lista de items
        items: list[OrderItemDetail] = []
        for detalle, producto in detalles:
            items.append(
                OrderItemDetail(
                    productId=int((producto.idProducto if producto else detalle.productoID) or 0),
                    name=str((producto.nombreProducto if producto else None) or "Producto"),
                    qty=int(detalle.cantidad or 0),
                    imageUrl=(
                        str(getattr(producto, "imageUrl", None))
                        if producto and getattr(producto, "imageUrl", None)
                        else None
                    ),
                )
            )
        
        # Construir respuesta con formato correcto
        numero_pedido_str = str(pedido.codigoPedido or pedido.numeroPedido or pedido.idPedido)
        
        return DomicilioDetailResponse(
            idEntrega=int(entrega.idEntrega),
            numeroPedido=numero_pedido_str,
            cliente=cliente_nombre,
            items=items,
            customerMessage=(str(entrega.mensaje or "") or None),
        )
        
    except HTTPException:
        raise
    except Exception as e:
        domicilios_logger.error("Error obteniendo detalle de domicilio %s", entrega_id, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"code": "INTERNAL_ERROR", "message": "Error interno del servidor"},
        ) from e
