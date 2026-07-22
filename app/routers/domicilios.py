from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4
import os
import shutil

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import String, and_, bindparam, cast, func, null, or_, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, aliased

from app.core.logger import get_logger
from app.core.ordering import sort_operativo
from app.core.security import (
    assert_same_empresa,
    get_current_auth_context,
    is_empresa_admin_context,
    is_super_admin_context,
    pwd_context,
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
from app.models.rol import Rol
from app.models.usuario import Usuario
from app.schemas.domicilios import (
    AsignarDomiciliarioRequest,
    DomicilioDetailResponse,
    DomiciliarioCreateRequest,
    DomiciliarioCreateResponse,
    DomiciliarioDeleteResponse,
    DomiciliarioItem,
    DomiciliarioListResponse,
    DomiciliarioUpdateRequest,
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
    rango_hora = str(entrega.rangoHora or "").strip()
    match = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", rango_hora)
    if match:
        return f"{int(match.group(1)):02d}:{match.group(2)}"
    if rango_hora:
        return rango_hora

    fecha_programada = _fecha_entrega_programada(entrega)
    if fecha_programada:
        return fecha_programada.strftime("%H:%M")

    return None


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
    return query.outerjoin(Barrio, barrio_match)


def _unpack_delivery_row(row):
    if len(row) == 6:
        return row
    entrega, pedido, cliente, produccion = row
    return entrega, pedido, cliente, produccion, None, None


def _clean_product_summary(value: str | None) -> str | None:
    summary = str(value or "").strip()
    if not summary:
        return None
    if summary.lower().startswith("pedido "):
        return None
    return summary


def _build_pedido_disponible_item(
    entrega: Entrega,
    pedido: Pedido,
    cliente: Cliente | None,
    produccion: Produccion | None,
    barrio: Barrio | None = None,
    zona: Zona | None = None,
    arreglo: str | None = None,
    productos: list[str] | None = None,
    image_url: str | None = None,
) -> PedidoDisponibleItem:
    arreglo = _clean_product_summary(arreglo)
    return PedidoDisponibleItem(
        id=int(pedido.idPedido),
        numeroPedido=_numero_pedido_api(pedido),
        codigoPedido=(str(pedido.codigoPedido).strip() if pedido.codigoPedido else None),
        arreglo=arreglo,
        nombreArreglo=arreglo,
        producto=arreglo,
        productos=productos or [],
        imageUrl=image_url,
        imagenUrl=image_url,
        imagenProductoUrl=image_url,
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
    image_url: str | None = None,
    arreglo: str | None = None,
    productos: list[str] | None = None,
) -> DomicilioCourierCard:
    arreglo = _clean_product_summary(arreglo)
    lat_destino, lng_destino = domicilio_service.payload_destino_lat_lng(entrega)
    lat, lng = domicilio_service.payload_lat_lng(entrega)
    return DomicilioCourierCard(
        idEntrega=int(entrega.idEntrega),
        pedidoID=int(entrega.pedidoID),
        numeroPedido=_numero_pedido_api(pedido),
        codigoPedido=(str(pedido.codigoPedido) if pedido.codigoPedido else None),
        arreglo=arreglo,
        nombreArreglo=arreglo,
        producto=arreglo,
        productos=productos or [],
        imageUrl=image_url,
        imagenUrl=image_url,
        imagenProductoUrl=image_url,
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


def _visible_product_code(codigo_producto: str | None, codigo_catalogo: str | None, empresa_id: int) -> str | None:
    catalog_code = str(codigo_catalogo or "").strip() or None
    product_code = str(codigo_producto or "").strip() or None
    if int(empresa_id) == 3 and catalog_code:
        return catalog_code
    return product_code


def _product_label(
    nombre: str | None,
    cantidad,
    codigo_producto: str | None = None,
    codigo_catalogo: str | None = None,
    empresa_id: int | None = None,
) -> str | None:
    nombre_limpio = str(nombre or "").strip()
    if not nombre_limpio:
        return None

    codigo = _visible_product_code(codigo_producto, codigo_catalogo, int(empresa_id or 0))
    product_text = f"{codigo} - {nombre_limpio}" if codigo else nombre_limpio

    try:
        qty = float(cantidad or 0)
    except (TypeError, ValueError):
        qty = 0

    if qty > 1:
        qty_text = str(int(qty)) if qty.is_integer() else str(qty)
        return f"{qty_text} x {product_text}"
    return product_text


def _pedido_product_payload_map(
    db: Session,
    empresa_id: int,
    pedido_ids: list[int],
    detalle_id_to_pedido_id: dict[int, int] | None = None,
) -> dict[int, dict]:
    detalle_id_to_pedido_id = detalle_id_to_pedido_id or {}
    if not pedido_ids and not detalle_id_to_pedido_id:
        return {}

    query = text(
        """
        SELECT
            pd.id_pedido_detalle,
            pd.pedido_id,
            p.codigo_producto,
            p.codigo_catalogo,
            p.nombre_producto,
            pd.cantidad
        FROM petalops.pedido_detalle pd
        LEFT JOIN petalops.producto p
          ON p.id_producto = pd.producto_id
        WHERE pd.pedido_id IN :pedido_ids
           OR pd.id_pedido_detalle IN :detalle_ids
        ORDER BY pd.pedido_id ASC, pd.id_pedido_detalle ASC
        """
    ).bindparams(
        bindparam("pedido_ids", expanding=True),
        bindparam("detalle_ids", expanding=True),
    )
    rows = db.execute(
        query,
        {
            "pedido_ids": [int(pedido_id) for pedido_id in pedido_ids] or [-1],
            "detalle_ids": list(detalle_id_to_pedido_id.keys()) or [-1],
        },
    ).all()

    payload_by_pedido: dict[int, dict] = {}
    for (
        detalle_id,
        pedido_id,
        codigo_producto,
        codigo_catalogo,
        nombre_producto,
        cantidad,
    ) in rows:
        pedido_id_value = pedido_id
        if pedido_id_value is None and detalle_id is not None:
            pedido_id_value = detalle_id_to_pedido_id.get(int(detalle_id))
        if pedido_id_value is None:
            continue

        pedido_id_int = int(pedido_id_value)
        payload = payload_by_pedido.setdefault(
            pedido_id_int,
            {"productos": [], "arreglo": None, "imageUrl": None},
        )
        label = _product_label(
            nombre_producto,
            cantidad,
            codigo_producto=codigo_producto,
            codigo_catalogo=codigo_catalogo,
            empresa_id=empresa_id,
        )
        if label:
            payload["productos"].append(label)

    try:
        image_query = text(
            """
            SELECT
                pd.id_pedido_detalle,
                pd.pedido_id,
                ps.imagen_url
            FROM petalops.pedido_detalle pd
            JOIN petalops.producto_sucursal ps
              ON ps.producto_id = pd.producto_id
             AND ps.sucursal_id = pd.sucursal_id
            WHERE (pd.pedido_id IN :pedido_ids OR pd.id_pedido_detalle IN :detalle_ids)
              AND ps.imagen_url IS NOT NULL
            ORDER BY pd.pedido_id ASC, pd.id_pedido_detalle ASC
            """
        ).bindparams(
            bindparam("pedido_ids", expanding=True),
            bindparam("detalle_ids", expanding=True),
        )
        image_rows = db.execute(
            image_query,
            {
                "pedido_ids": [int(pedido_id) for pedido_id in pedido_ids] or [-1],
                "detalle_ids": list(detalle_id_to_pedido_id.keys()) or [-1],
            },
        ).all()
        for detalle_id, pedido_id, image_url in image_rows:
            pedido_id_value = pedido_id
            if pedido_id_value is None and detalle_id is not None:
                pedido_id_value = detalle_id_to_pedido_id.get(int(detalle_id))
            if pedido_id_value is None or not image_url:
                continue
            payload = payload_by_pedido.setdefault(
                int(pedido_id_value),
                {"productos": [], "arreglo": None, "imageUrl": None},
            )
            if not payload["imageUrl"]:
                payload["imageUrl"] = str(image_url)
    except SQLAlchemyError:
        domicilios_logger.error("No fue posible enriquecer domicilios con imagen de producto. empresa_id=%s", empresa_id, exc_info=True)

    for payload in payload_by_pedido.values():
        payload["arreglo"] = ", ".join(payload["productos"]) if payload["productos"] else None
    return payload_by_pedido


def _build_courier_cards_with_images(
    db: Session,
    empresa_id: int,
    rows,
) -> list[DomicilioCourierCard]:
    unpacked_rows = [_unpack_delivery_row(row) for row in rows]
    detalle_id_to_pedido_id = {
        int(produccion.pedidoDetalleID): int(pedido.idPedido)
        for _entrega, pedido, _cliente, produccion, _barrio, _zona in unpacked_rows
        if produccion and getattr(produccion, "pedidoDetalleID", None) is not None
    }
    try:
        product_by_pedido = _pedido_product_payload_map(
            db,
            empresa_id,
            [int(pedido.idPedido) for _entrega, pedido, _cliente, _produccion, _barrio, _zona in unpacked_rows],
            detalle_id_to_pedido_id=detalle_id_to_pedido_id,
        )
    except SQLAlchemyError:
        domicilios_logger.error("No fue posible enriquecer domicilios con productos. empresa_id=%s", empresa_id, exc_info=True)
        product_by_pedido = {}
    items: list[DomicilioCourierCard] = []
    for entrega, pedido, cliente, produccion, barrio, zona in unpacked_rows:
        product_payload = product_by_pedido.get(int(pedido.idPedido), {})
        items.append(_build_courier_card(
            entrega,
            pedido,
            cliente,
            produccion,
            barrio,
            zona,
            image_url=product_payload.get("imageUrl"),
            arreglo=product_payload.get("arreglo"),
            productos=product_payload.get("productos") or [],
        ))
    return items


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
    direccion_norm = func.lower(
        func.replace(
            func.replace(func.coalesce(entrega_actual.direccion, ""), "-", "_"),
            " ",
            "_",
        )
    )

    q = (
        db.query(entrega_actual, Pedido, Cliente, Produccion, Barrio, null().label("zona"))
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
        db.query(entrega_actual, Pedido, Cliente, Produccion, Barrio, null().label("zona"))
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
            direccion_norm.notin_(domicilio_service.STORE_PICKUP_TIPO_ENTREGA_VALUES),
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
    direccion_norm = func.lower(
        func.replace(
            func.replace(func.coalesce(entrega_actual.direccion, ""), "-", "_"),
            " ",
            "_",
        )
    )

    q = (
        db.query(entrega_actual, Pedido, Cliente, Produccion, Barrio, null().label("zona"))
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
            direccion_norm.notin_(domicilio_service.STORE_PICKUP_TIPO_ENTREGA_VALUES),
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


def _listar_pedidos_disponibles_api_rows(
    db: Session,
    empresa_id: int,
    sucursal_id: int | None,
    fecha_desde: datetime,
    fecha_hasta: datetime,
    page: int,
    page_size: int,
) -> list[PedidoDisponibleItem]:
    estado_para_entrega = produccion_service.estado_produccion_id(db, produccion_service.ESTADO_PARA_ENTREGA)
    estado_pendiente_id = domicilio_service.resolve_estado_entrega_id(db, ESTADO_PENDIENTE)

    query = text(
        """
        WITH latest_attempt AS (
            SELECT pedido_id, MAX(intentonumero) AS max_intento
            FROM petalops.entrega
            WHERE empresa_id = :empresa_id
            GROUP BY pedido_id
        ),
        latest_entrega AS (
            SELECT e.pedido_id, MAX(e.id_entrega) AS entrega_id
            FROM petalops.entrega e
            JOIN latest_attempt la
              ON la.pedido_id = e.pedido_id
             AND la.max_intento = e.intentonumero
            WHERE e.empresa_id = :empresa_id
            GROUP BY e.pedido_id
        ),
        base AS (
            SELECT
                e.id_entrega,
                e.produccionid,
                e.pedido_id,
                e.empresa_id,
                COALESCE(e.sucursalid, p.sucursal_id) AS sucursal_id,
                e.destinatario,
                e.telefonodestino,
                e.direccion,
                e.barrioid,
                e.barrionombre,
                e.rangohora,
                e.mensaje,
                COALESCE(e.observaciongeneral, e.observaciones) AS observacion,
                e.latituddestino,
                e.longituddestino,
                COALESCE(e.reprogramadapara, e.fechaentregaprogramada, e.fechaentrega) AS fecha_programada,
                p.numero_pedido,
                p.codigo_pedido,
                c.nombre_completo AS cliente,
                pr.pedido_detalle_id,
                pr.prioridad,
                b.id_barrio,
                b.nombre_barrio,
                b.zona_id,
                z.nombre_zona
            FROM petalops.entrega e
            JOIN latest_entrega le ON le.entrega_id = e.id_entrega
            JOIN petalops.pedido p ON p.id_pedido = e.pedido_id
            JOIN petalops.cliente c ON c.cliente_id = p.cliente_id
            JOIN petalops.produccion pr ON pr.id_produccion = e.produccionid
            LEFT JOIN petalops.barrio b
              ON (
                    e.barrioid IS NOT NULL
                AND b.empresa_id = e.empresa_id
                AND b.id_barrio = e.barrioid
              )
              OR (
                    e.barrioid IS NULL
                AND b.empresa_id = e.empresa_id
                AND lower(b.nombre_barrio) = lower(e.barrionombre)
                AND (b.sucursal_id IS NULL OR b.sucursal_id = COALESCE(e.sucursalid, p.sucursal_id))
              )
            LEFT JOIN petalops.zona z ON z.id_zona = b.zona_id
            WHERE e.empresa_id = :empresa_id
              AND e.domiciliarioid IS NULL
              AND e.estadoentregaid = :estado_pendiente_id
              AND pr.estado_produccion_id = :estado_para_entrega
              AND COALESCE(e.reprogramadapara, e.fechaentregaprogramada, e.fechaentrega)
                  BETWEEN :fecha_desde AND :fecha_hasta
              AND lower(replace(replace(COALESCE(e.tipoentrega, ''), '-', '_'), ' ', '_'))
                  NOT IN :store_pickup_values
              AND (:sucursal_id IS NULL OR COALESCE(e.sucursalid, p.sucursal_id) = :sucursal_id)
        ),
        productos AS (
            SELECT
                b.pedido_id,
                string_agg(
                    (
                        CASE
                            WHEN COALESCE(pd.cantidad, 0) > 1
                                THEN (
                                    CASE
                                        WHEN pd.cantidad = trunc(pd.cantidad)
                                            THEN trunc(pd.cantidad)::text
                                        ELSE pd.cantidad::text
                                    END
                                ) || ' x '
                            ELSE ''
                        END
                    ) ||
                    (
                        CASE
                            WHEN COALESCE(
                                CASE WHEN :empresa_id = 3 THEN NULLIF(prod.codigo_catalogo, '') END,
                                NULLIF(prod.codigo_producto, '')
                            ) IS NOT NULL
                                THEN COALESCE(
                                    CASE WHEN :empresa_id = 3 THEN NULLIF(prod.codigo_catalogo, '') END,
                                    NULLIF(prod.codigo_producto, '')
                                ) || ' - '
                            ELSE ''
                        END
                    ) ||
                    COALESCE(NULLIF(prod.nombre_producto, ''), 'Producto'),
                    ', '
                    ORDER BY pd.id_pedido_detalle
                ) AS arreglo,
                (
                    array_agg(
                        ps.imagen_url
                        ORDER BY pd.id_pedido_detalle
                    )
                    FILTER (WHERE ps.imagen_url IS NOT NULL)
                )[1] AS image_url
            FROM base b
            JOIN petalops.pedido_detalle pd
              ON pd.pedido_id = b.pedido_id
              OR pd.id_pedido_detalle = b.pedido_detalle_id
            LEFT JOIN petalops.producto prod ON prod.id_producto = pd.producto_id
            LEFT JOIN petalops.producto_sucursal ps
              ON ps.producto_id = pd.producto_id
             AND ps.sucursal_id = b.sucursal_id
            GROUP BY b.pedido_id
        )
        SELECT
            b.*,
            productos.arreglo,
            productos.image_url
        FROM base b
        LEFT JOIN productos ON productos.pedido_id = b.pedido_id
        ORDER BY b.fecha_programada ASC, b.id_entrega ASC
        OFFSET :offset_rows
        LIMIT :limit_rows
        """
    ).bindparams(bindparam("store_pickup_values", expanding=True))

    rows = db.execute(
        query,
        {
            "empresa_id": int(empresa_id),
            "sucursal_id": int(sucursal_id) if sucursal_id is not None else None,
            "estado_pendiente_id": int(estado_pendiente_id),
            "estado_para_entrega": int(estado_para_entrega),
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "store_pickup_values": tuple(sorted(domicilio_service.STORE_PICKUP_TIPO_ENTREGA_VALUES)),
            "offset_rows": int((page - 1) * page_size),
            "limit_rows": int(page_size),
        },
    ).mappings().all()

    items: list[PedidoDisponibleItem] = []
    for row in rows:
        arreglo = _clean_product_summary(row.get("arreglo"))
        productos = [arreglo] if arreglo else []
        codigo_pedido = str(row.get("codigo_pedido") or "").strip() or None
        numero_pedido = codigo_pedido or str(row.get("numero_pedido") or row.get("pedido_id"))
        barrio_id = row.get("id_barrio") or row.get("barrioid")
        nombre_barrio = str(row.get("nombre_barrio") or row.get("barrionombre") or "").strip() or None
        zona_id = row.get("zona_id")
        nombre_zona = str(row.get("nombre_zona") or "").strip() or None

        items.append(
            PedidoDisponibleItem(
                id=int(row["pedido_id"]),
                idEntrega=int(row["id_entrega"]),
                pedidoID=int(row["pedido_id"]),
                produccionID=(int(row["produccionid"]) if row.get("produccionid") is not None else None),
                numeroPedido=numero_pedido,
                codigoPedido=codigo_pedido,
                arreglo=arreglo,
                nombreArreglo=arreglo,
                producto=arreglo,
                productos=productos,
                imageUrl=(str(row.get("image_url")) if row.get("image_url") else None),
                imagenUrl=(str(row.get("image_url")) if row.get("image_url") else None),
                imagenProductoUrl=(str(row.get("image_url")) if row.get("image_url") else None),
                cliente=str(row.get("cliente") or "Cliente"),
                destinatario=str(row.get("destinatario") or "") or None,
                telefonoDestino=str(row.get("telefonodestino") or "") or None,
                telefonoDestinatario=str(row.get("telefonodestino") or "") or None,
                celularDestinatario=str(row.get("telefonodestino") or "") or None,
                direccion=str(row.get("direccion") or "") or None,
                mensaje=str(row.get("mensaje") or "") or None,
                observacion=str(row.get("observacion") or "") or None,
                horaEntrega=str(row.get("rangohora") or "") or None,
                fechaEntregaProgramada=row.get("fecha_programada"),
                barrioId=(int(barrio_id) if barrio_id is not None else None),
                nombreBarrio=nombre_barrio,
                barrio=nombre_barrio,
                zonaId=(int(zona_id) if zona_id is not None else None),
                nombreZona=nombre_zona,
                zona=nombre_zona,
                estado="SIN_ASIGNAR",
                prioridad=(str(row.get("prioridad") or "") or None),
                latitudDestino=(float(row["latituddestino"]) if row.get("latituddestino") is not None else None),
                longitudDestino=(float(row["longituddestino"]) if row.get("longituddestino") is not None else None),
            )
        )
    return items


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


def _domiciliario_estado(row: Domiciliario) -> str:
    estado = str(getattr(row, "estado", "") or "").strip()
    if estado:
        return estado
    return "Activo" if bool(row.activo) else "Inactivo"


def _domiciliario_item(row: Domiciliario, pedidos_activos: int = 0) -> DomiciliarioItem:
    return DomiciliarioItem(
        idDomiciliario=int(row.idDomiciliario),
        usuarioID=(int(row.usuarioID) if getattr(row, "usuarioID", None) is not None else None),
        login=(str(row.usuario).strip() if getattr(row, "usuario", None) else None),
        nombre=str(row.nombre or ""),
        telefono=(str(row.telefono).strip() if getattr(row, "telefono", None) else None),
        tipo=(str(row.tipo).strip() if getattr(row, "tipo", None) else "Interno"),
        estado=_domiciliario_estado(row),
        vehiculo=(str(row.vehiculo).strip() if getattr(row, "vehiculo", None) else None),
        placa=(str(row.placa).strip() if getattr(row, "placa", None) else None),
        detalleVehiculo=(str(row.detalleVehiculo).strip() if getattr(row, "detalleVehiculo", None) else None),
        pedidosActivos=int(pedidos_activos),
        activo=bool(row.activo),
    )


def _assert_admin_can_manage_domiciliarios(auth):
    if not _actor_can_override_delivery(auth):
        raise _err(
            "DOMICILIARIO_ADMIN_REQUIRED",
            "Solo un administrador puede editar domiciliarios",
            status_code=403,
        )


def _normalize_login_part(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", ascii_value.lower())


def _base_login_from_name(nombre: str) -> str:
    parts = [_normalize_login_part(part) for part in str(nombre or "").strip().split()]
    parts = [part for part in parts if part]
    if len(parts) >= 2:
        return f"{parts[0][0]}{parts[1]}"[:70]
    if parts:
        return parts[0][:70]
    return "domiciliario"


def _default_domiciliario_password(nombre: str) -> str:
    first_name = str(nombre or "").strip().split()[0]
    normalized = unicodedata.normalize("NFKD", first_name)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    clean = re.sub(r"[^A-Za-z0-9]+", "", ascii_value)
    if not clean:
        clean = "Domiciliario"
    return f"{clean[:1].upper()}{clean[1:].lower()}123"


def _next_unique_domiciliario_login(db: Session, empresa_id: int, nombre: str) -> str:
    base = _base_login_from_name(nombre)
    login = base
    suffix = 1
    while True:
        existing_user = (
            db.query(Usuario.idusuario)
            .filter(func.lower(Usuario.login) == login.lower())
            .first()
        )
        existing_employee = (
            db.query(Domiciliario.idDomiciliario)
            .filter(
                Domiciliario.empresaID == int(empresa_id),
                func.lower(func.coalesce(Domiciliario.usuario, "")) == login.lower(),
            )
            .first()
        )
        if not existing_user and not existing_employee:
            return login
        suffix += 1
        login = f"{base}{suffix}"


def _validate_domiciliario_estado(raw_estado: str | None, activo: bool | None = None) -> tuple[str, int]:
    estado = str(raw_estado or "").strip().title()
    if not estado:
        estado = "Activo" if activo is not False else "Inactivo"
    if estado not in {"Activo", "Inactivo", "Eliminado"}:
        raise _err("DOMICILIARIO_ESTADO_INVALID", "Estado debe ser Activo, Inactivo o Eliminado", status_code=400)
    if activo is not None:
        return ("Activo" if activo else "Inactivo") if raw_estado is None else estado, (1 if activo else 0)
    return estado, (1 if estado == "Activo" else 0)


def _resolve_domiciliario_role(db: Session, empresa_id: int) -> Rol:
    rol = (
        db.query(Rol)
        .filter(Rol.empresaID == int(empresa_id), func.lower(Rol.nombreRol) == "domiciliario")
        .first()
    )
    if rol:
        return rol

    rol = Rol(empresaID=int(empresa_id), nombreRol="Domiciliario")
    db.add(rol)
    db.flush()
    return rol


@router.get("/domiciliarios", response_model=DomiciliarioListResponse)
def listar_domiciliarios(
    empresa_id: int = Query(..., alias="empresaID"),
    sucursal_id: int | None = Query(None, alias="sucursalID"),
    solo_activos: bool = Query(True, alias="soloActivos"),
    estado: str | None = Query(None),
    search_term: str | None = Query(None, alias="q"),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)
    q = db.query(Domiciliario).filter(Domiciliario.empresaID == int(empresa_id))
    q = q.filter(func.upper(Domiciliario.cargo) == "DOMICILIARIO")
    if sucursal_id is not None:
        q = q.filter(Domiciliario.sucursalID == int(sucursal_id))

    estado_filter = str(estado or "").strip().lower()
    if solo_activos and not estado_filter:
        q = q.filter(_activo_truthy(Domiciliario.activo))
        q = q.filter(func.lower(func.coalesce(Domiciliario.estado, "Activo")) != "eliminado")

    if estado_filter and estado_filter not in {"todos", "todos los estados"}:
        if estado_filter == "activo":
            q = q.filter(_activo_truthy(Domiciliario.activo))
            q = q.filter(func.lower(func.coalesce(Domiciliario.estado, "Activo")) != "eliminado")
        elif estado_filter == "inactivo":
            q = q.filter(or_(Domiciliario.activo == 0, func.lower(Domiciliario.estado) == "inactivo"))
        elif estado_filter == "eliminado":
            q = q.filter(func.lower(Domiciliario.estado) == "eliminado")
        else:
            raise _err("DOMICILIARIO_ESTADO_FILTER_INVALID", "Filtro de estado invalido", status_code=400)

    search = str(search_term or "").strip()
    if search:
        pattern = f"%{search}%"
        q = q.filter(
            or_(
                cast(Domiciliario.idDomiciliario, String).ilike(pattern),
                Domiciliario.nombre.ilike(pattern),
                Domiciliario.telefono.ilike(pattern),
                Domiciliario.tipo.ilike(pattern),
                Domiciliario.vehiculo.ilike(pattern),
            )
        )

    rows = q.order_by(Domiciliario.nombre.asc()).all()
    return DomiciliarioListResponse(
        items=[
            _domiciliario_item(
                row,
                domicilio_service.count_entregas_activas(
                    db=db,
                    empresa_id=int(empresa_id),
                    sucursal_id=(int(row.sucursalID) if row.sucursalID is not None else None),
                    domiciliario_id=int(row.idDomiciliario),
                ),
            )
            for row in rows
        ]
    )


@router.post(
    "/domiciliarios",
    response_model=DomiciliarioCreateResponse,
    dependencies=[Depends(require_module_access("domicilios", "puedeEditar"))],
)
def crear_domiciliario(
    payload: DomiciliarioCreateRequest,
    empresa_id: int = Query(..., alias="empresaID"),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)
    _assert_admin_can_manage_domiciliarios(auth)

    nombre = payload.nombre.strip()
    if not nombre:
        raise _err("DOMICILIARIO_NOMBRE_INVALID", "Nombre de domiciliario invalido", status_code=400)

    sucursal_id = int(payload.sucursalID if payload.sucursalID is not None else (auth.sucursalID or 0))
    if not sucursal_id:
        raise _err("DOMICILIARIO_SUCURSAL_REQUIRED", "Sucursal requerida para crear domiciliario", status_code=400)

    sucursal = (
        db.query(Sucursal)
        .filter(Sucursal.idSucursal == int(sucursal_id), Sucursal.empresaID == int(empresa_id))
        .first()
    )
    if not sucursal:
        raise _err("DOMICILIARIO_SUCURSAL_INVALID", "Sucursal invalida para la empresa", status_code=400)

    estado, activo_flag = _validate_domiciliario_estado(payload.estado, payload.activo)
    login = _next_unique_domiciliario_login(db, int(empresa_id), nombre)
    email = f"{login}@petalops.local"
    password_temporal = _default_domiciliario_password(nombre)
    password_hash = pwd_context.hash(password_temporal)
    rol = _resolve_domiciliario_role(db, int(empresa_id))

    usuario = Usuario(
        empresaID=int(empresa_id),
        sucursalID=int(sucursal_id),
        nombre=nombre,
        login=login,
        email=email,
        passwordHash=password_hash,
        rolID=int(rol.idRol),
        estado=estado,
        esSuperadmin=False,
        createdAt=datetime.now(timezone.utc),
        updatedAt=datetime.now(timezone.utc),
    )
    db.add(usuario)
    db.flush()

    domiciliario = Domiciliario(
        empresaID=int(empresa_id),
        sucursalID=int(sucursal_id),
        usuarioID=int(usuario.idusuario),
        nombre=nombre,
        cargo="Domiciliario",
        usuario=login,
        email=email,
        passwordHash=password_hash,
        telefono=(payload.telefono.strip() if payload.telefono else None),
        tipo=(payload.tipo.strip() if payload.tipo else "Interno"),
        estado=estado,
        vehiculo=(payload.vehiculo.strip() if payload.vehiculo else None),
        placa=(payload.placa.strip() if payload.placa else None),
        detalleVehiculo=(payload.detalleVehiculo.strip() if payload.detalleVehiculo else None),
        activo=activo_flag,
        createdAt=datetime.now(timezone.utc),
        updatedAt=datetime.now(timezone.utc),
    )
    db.add(domiciliario)
    db.commit()
    db.refresh(domiciliario)

    item = _domiciliario_item(domiciliario, pedidos_activos=0)
    return DomiciliarioCreateResponse(**item.model_dump(), passwordTemporal=password_temporal)


@router.put(
    "/domiciliarios/{domiciliario_id}",
    response_model=DomiciliarioItem,
    dependencies=[Depends(require_module_access("domicilios", "puedeEditar"))],
)
def actualizar_domiciliario(
    domiciliario_id: int,
    payload: DomiciliarioUpdateRequest,
    empresa_id: int = Query(..., alias="empresaID"),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)
    _assert_admin_can_manage_domiciliarios(auth)

    domiciliario = (
        db.query(Domiciliario)
        .filter(
            Domiciliario.idDomiciliario == int(domiciliario_id),
            Domiciliario.empresaID == int(empresa_id),
            func.upper(Domiciliario.cargo) == "DOMICILIARIO",
        )
        .first()
    )
    if not domiciliario:
        raise _err("DOMICILIARIO_NOT_FOUND", "Domiciliario no encontrado", status_code=404)

    has_changes = False

    if payload.nombre is not None:
        nombre = payload.nombre.strip()
        if not nombre:
            raise _err("DOMICILIARIO_NOMBRE_INVALID", "Nombre de domiciliario invalido", status_code=400)
        domiciliario.nombre = nombre
        has_changes = True

    if payload.sucursalID is not None:
        sucursal = (
            db.query(Sucursal)
            .filter(
                Sucursal.idSucursal == int(payload.sucursalID),
                Sucursal.empresaID == int(empresa_id),
            )
            .first()
        )
        if not sucursal:
            raise _err("DOMICILIARIO_SUCURSAL_INVALID", "Sucursal invalida para la empresa", status_code=400)
        domiciliario.sucursalID = int(payload.sucursalID)
        has_changes = True

    if payload.telefono is not None:
        telefono = payload.telefono.strip()
        domiciliario.telefono = telefono or None
        has_changes = True

    if payload.tipo is not None:
        tipo = payload.tipo.strip()
        domiciliario.tipo = tipo or None
        has_changes = True

    if payload.estado is not None:
        estado, activo_flag = _validate_domiciliario_estado(payload.estado)
        domiciliario.estado = estado
        domiciliario.activo = activo_flag
        has_changes = True

    if payload.vehiculo is not None:
        vehiculo = payload.vehiculo.strip()
        domiciliario.vehiculo = vehiculo or None
        has_changes = True

    if payload.placa is not None:
        placa = payload.placa.strip()
        domiciliario.placa = placa or None
        has_changes = True

    if payload.detalleVehiculo is not None:
        detalle_vehiculo = payload.detalleVehiculo.strip()
        domiciliario.detalleVehiculo = detalle_vehiculo or None
        has_changes = True

    if payload.activo is not None:
        domiciliario.activo = 1 if payload.activo else 0
        if payload.estado is None:
            domiciliario.estado = "Activo" if payload.activo else "Inactivo"
        has_changes = True

    if not has_changes:
        raise _err("DOMICILIARIO_UPDATE_EMPTY", "No hay campos para actualizar", status_code=400)

    domiciliario.updatedAt = datetime.now(timezone.utc)
    db.commit()
    db.refresh(domiciliario)

    pedidos_activos = domicilio_service.count_entregas_activas(
        db=db,
        empresa_id=int(empresa_id),
        sucursal_id=(int(domiciliario.sucursalID) if domiciliario.sucursalID is not None else None),
        domiciliario_id=int(domiciliario.idDomiciliario),
    )
    return _domiciliario_item(domiciliario, pedidos_activos=pedidos_activos)


@router.delete(
    "/domiciliarios/{domiciliario_id}",
    response_model=DomiciliarioDeleteResponse,
    dependencies=[Depends(require_module_access("domicilios", "puedeEditar"))],
)
def eliminar_domiciliario(
    domiciliario_id: int,
    empresa_id: int = Query(..., alias="empresaID"),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)
    _assert_admin_can_manage_domiciliarios(auth)

    domiciliario = (
        db.query(Domiciliario)
        .filter(
            Domiciliario.idDomiciliario == int(domiciliario_id),
            Domiciliario.empresaID == int(empresa_id),
            func.upper(Domiciliario.cargo) == "DOMICILIARIO",
        )
        .first()
    )
    if not domiciliario:
        raise _err("DOMICILIARIO_NOT_FOUND", "Domiciliario no encontrado", status_code=404)

    pedidos_activos = domicilio_service.count_entregas_activas(
        db=db,
        empresa_id=int(empresa_id),
        sucursal_id=(int(domiciliario.sucursalID) if domiciliario.sucursalID is not None else None),
        domiciliario_id=int(domiciliario.idDomiciliario),
    )
    if pedidos_activos > 0:
        raise _err(
            "DOMICILIARIO_DELETE_HAS_ACTIVE_ORDERS",
            "No se puede eliminar un domiciliario con pedidos activos",
            status_code=409,
        )

    domiciliario.activo = 0
    domiciliario.estado = "Eliminado"
    domiciliario.updatedAt = datetime.now(timezone.utc)
    db.commit()

    return DomiciliarioDeleteResponse(
        status="ok",
        idDomiciliario=int(domiciliario.idDomiciliario),
        estado="Eliminado",
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
        db.query(entrega_actual, Pedido, Cliente, Produccion, Domiciliario, Barrio, null().label("zona"))
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
    "/{entrega_id}/devolver",
    response_model=DomicilioActionResponse,
    dependencies=[Depends(require_module_access("domicilios", "puedeEditar"))],
)
def devolver_entrega(
    entrega_id: int,
    payload: TomarEntregaRequest,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    entrega = _locked_current_entrega(db, int(auth.empresaID), entrega_id)
    assert_same_empresa(auth, int(entrega.empresaID))
    _assert_entrega_actor_scope(entrega, auth, db)

    actual = domicilio_service.estado_norm(entrega.estadoEntregaID)
    if actual not in {ESTADO_ASIGNADO, ESTADO_NO_ENTREGADO}:
        raise _err(
            "DOMICILIO_DEVOLVER_INVALID",
            f"No se puede devolver entrega desde estado {actual}",
            status_code=400,
        )

    entrega.domiciliarioID = None
    entrega.fechaAsignacion = None
    entrega.fechaSalida = None
    entrega.estadoEntregaID = domicilio_service.resolve_estado_entrega_id(db, ESTADO_PENDIENTE)
    entrega.updatedAt = datetime.now(timezone.utc)
    db.commit()

    return DomicilioActionResponse(status="ok", idEntrega=int(entrega.idEntrega), estado=ESTADO_PENDIENTE)


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
    items = _build_courier_cards_with_images(db, empresa_id, rows)
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
    items = _build_courier_cards_with_images(db, empresa_id, rows)
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
    unpacked_rows = [_unpack_delivery_row(row) for row in rows]
    detalle_id_to_pedido_id = {
        int(produccion.pedidoDetalleID): int(pedido.idPedido)
        for _entrega, pedido, _cliente, produccion, _barrio, _zona in unpacked_rows
        if produccion and getattr(produccion, "pedidoDetalleID", None) is not None
    }
    try:
        product_by_pedido = _pedido_product_payload_map(
            db,
            empresa_id,
            [int(pedido.idPedido) for _entrega, pedido, _cliente, _produccion, _barrio, _zona in unpacked_rows],
            detalle_id_to_pedido_id=detalle_id_to_pedido_id,
        )
    except SQLAlchemyError:
        domicilios_logger.error("No fue posible enriquecer pedidos disponibles con productos. empresa_id=%s", empresa_id, exc_info=True)
        product_by_pedido = {}
    for entrega, pedido, cliente, produccion, barrio, zona in unpacked_rows:
        product_payload = product_by_pedido.get(int(pedido.idPedido), {})
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
                image_url=product_payload.get("imageUrl"),
                arreglo=product_payload.get("arreglo"),
                productos=product_payload.get("productos") or [],
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
    unpacked_rows = [_unpack_delivery_row(row) for row in rows]
    detalle_id_to_pedido_id = {
        int(produccion.pedidoDetalleID): int(pedido.idPedido)
        for _entrega, pedido, _cliente, produccion, _barrio, _zona in unpacked_rows
        if produccion and getattr(produccion, "pedidoDetalleID", None) is not None
    }
    try:
        product_by_pedido = _pedido_product_payload_map(
            db,
            empresa_id,
            [int(pedido.idPedido) for _entrega, pedido, _cliente, _produccion, _barrio, _zona in unpacked_rows],
            detalle_id_to_pedido_id=detalle_id_to_pedido_id,
        )
    except SQLAlchemyError:
        domicilios_logger.error("No fue posible enriquecer pedidos disponibles API con productos. empresa_id=%s", empresa_id, exc_info=True)
        product_by_pedido = {}
    items: list[PedidoDisponibleItem] = []
    for entrega, pedido, cliente, produccion, barrio, zona in unpacked_rows:
        product_payload = product_by_pedido.get(int(pedido.idPedido), {})
        image_url = product_payload.get("imageUrl")
        arreglo = product_payload.get("arreglo")
        productos = product_payload.get("productos") or []
        lat_destino, lng_destino = domicilio_service.payload_destino_lat_lng(entrega)
        location = _location_payload(entrega, barrio, zona)
        items.append(
            PedidoDisponibleItem(
                id=int(pedido.idPedido),
                idEntrega=int(entrega.idEntrega),
                pedidoID=int(pedido.idPedido),
                produccionID=(int(entrega.produccionID) if entrega.produccionID is not None else None),
                numeroPedido=_numero_pedido_api(pedido),
                codigoPedido=(str(pedido.codigoPedido).strip() if pedido.codigoPedido else None),
                arreglo=arreglo,
                nombreArreglo=arreglo,
                producto=arreglo,
                productos=productos,
                imageUrl=image_url,
                imagenUrl=image_url,
                imagenProductoUrl=image_url,
                cliente=str((cliente.nombreCompleto if cliente else None) or "Cliente"),
                destinatario=str(entrega.destinatario or "") or None,
                telefonoDestino=str(entrega.telefonoDestino or "") or None,
                telefonoDestinatario=str(entrega.telefonoDestino or "") or None,
                celularDestinatario=str(entrega.telefonoDestino or "") or None,
                direccion=(str(entrega.direccion).strip() if entrega.direccion else None),
                mensaje=str(entrega.mensaje or "") or None,
                observacion=(str(entrega.observacionGeneral or entrega.observaciones or "").strip() or None),
                horaEntrega=_hora_entrega_hhmm(entrega),
                fechaEntregaProgramada=_fecha_entrega_programada(entrega),
                barrioId=location["barrioId"],
                nombreBarrio=location["nombreBarrio"],
                barrio=location["barrio"],
                zonaId=location["zonaId"],
                nombreZona=location["nombreZona"],
                zona=location["zona"],
                estado=_estado_api(entrega),
                prioridad=(str(produccion.prioridad or "") if produccion and produccion.prioridad else None),
                latitudDestino=lat_destino,
                longitudDestino=lng_destino,
            )
        )
    return items


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
    detalle_id_to_pedido_id = {}
    if produccion and getattr(produccion, "pedidoDetalleID", None) is not None:
        detalle_id_to_pedido_id[int(produccion.pedidoDetalleID)] = int(pedido.idPedido)
    try:
        product_payload = _pedido_product_payload_map(
            db,
            empresa_id,
            [int(pedido.idPedido)],
            detalle_id_to_pedido_id=detalle_id_to_pedido_id,
        ).get(int(pedido.idPedido), {})
    except SQLAlchemyError:
        domicilios_logger.error("No fue posible enriquecer pedido asignado con productos. pedido_id=%s", pedido.idPedido, exc_info=True)
        product_payload = {}
    base_item = _build_pedido_disponible_item(
        entrega,
        pedido,
        cliente,
        produccion,
        arreglo=product_payload.get("arreglo"),
        productos=product_payload.get("productos") or [],
        image_url=product_payload.get("imageUrl"),
    )
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
    items = _build_courier_cards_with_images(db, empresa_id, rows)
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
