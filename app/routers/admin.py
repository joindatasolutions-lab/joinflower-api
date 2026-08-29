from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import (
    assert_same_empresa,
    get_current_auth_context,
    is_empresa_admin_context,
    is_super_admin_context,
    require_module_access,
)
from app.database import get_db
from app.models.domiciliario import Domiciliario
from app.models.entrega import Entrega
from app.models.pedido import Pedido
from app.models.produccion import Produccion
from app.schemas.admin import (
    RegularizarEntregaItemResponse,
    RegularizarEntregaPedidoInput,
    RegularizarEntregasRequest,
    RegularizarEntregasResponse,
)
from app.schemas.domicilios import (
    ESTADO_ASIGNADO,
    ESTADO_EN_RUTA,
    ESTADO_ENTREGADO,
    ESTADO_PENDIENTE,
)
from app.services import domicilio_service, produccion_service
from app.routers import domicilios as domicilios_router


router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(require_module_access("domicilios", "puedeEditar"))],
)


def _err(code: str, message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "module": "admin"},
    )


def _assert_admin(auth):
    if not (is_super_admin_context(auth) or is_empresa_admin_context(auth)):
        raise _err(
            "ADMIN_REQUIRED",
            "Solo un administrador puede regularizar entregas historicas",
            status_code=403,
        )


def _regularizacion_items(payload: RegularizarEntregasRequest) -> list[RegularizarEntregaPedidoInput]:
    if payload.pedidos:
        return payload.pedidos
    if payload.pedido_id is not None and payload.hora_entrega is not None:
        return [
            RegularizarEntregaPedidoInput(
                pedido_id=int(payload.pedido_id),
                hora_entrega=payload.hora_entrega,
            )
        ]
    raise _err(
        "REGULARIZACION_PEDIDOS_REQUIRED",
        "Debe enviar pedidos o pedido_id/hora_entrega para regularizar",
        status_code=422,
    )


def _motivo_regularizacion(payload: RegularizarEntregasRequest) -> str:
    motivo = str(payload.motivo_regularizacion or payload.motivo or "").strip()
    if len(motivo) < 10:
        raise _err(
            "REGULARIZACION_MOTIVO_REQUIRED",
            "El motivo de regularizacion debe tener al menos 10 caracteres",
            status_code=422,
        )
    return motivo


def _naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _fecha_programada(entrega: Entrega | None, pedido: Pedido) -> datetime | None:
    value = (
        getattr(entrega, "reprogramadaPara", None)
        or getattr(entrega, "fechaEntregaProgramada", None)
        or getattr(entrega, "fechaEntrega", None)
        or getattr(pedido, "fechaPedido", None)
    )
    return _naive_utc(value)


def _timeline_for_regularizacion(programada: datetime, entregada: datetime) -> tuple[datetime, datetime]:
    if entregada < programada:
        raise _err(
            "REGULARIZACION_FECHA_ANTES_DE_PROGRAMADA",
            "La entrega no puede registrarse antes de la fecha y hora programada del pedido",
            status_code=400,
        )

    if entregada == programada:
        return programada, programada

    fecha_asignacion = max(programada, entregada - timedelta(minutes=35))
    fecha_salida = max(fecha_asignacion, entregada - timedelta(minutes=15))
    if fecha_salida > entregada:
        fecha_salida = entregada
    return fecha_asignacion, fecha_salida


def _snapshot_entrega(entrega: Entrega | None) -> dict:
    if entrega is None:
        return {}
    return {
        "entregaID": int(entrega.idEntrega) if getattr(entrega, "idEntrega", None) is not None else None,
        "domiciliarioID": int(entrega.domiciliarioID) if getattr(entrega, "domiciliarioID", None) is not None else None,
        "estado": domicilio_service.estado_norm(getattr(entrega, "estadoEntregaID", None)),
        "estadoEntregaID": int(entrega.estadoEntregaID) if getattr(entrega, "estadoEntregaID", None) is not None else None,
        "fechaAsignacion": entrega.fechaAsignacion.isoformat() if getattr(entrega, "fechaAsignacion", None) else None,
        "fechaSalida": entrega.fechaSalida.isoformat() if getattr(entrega, "fechaSalida", None) else None,
        "fechaEntregaProgramada": entrega.fechaEntregaProgramada.isoformat() if getattr(entrega, "fechaEntregaProgramada", None) else None,
        "fechaEntrega": entrega.fechaEntrega.isoformat() if getattr(entrega, "fechaEntrega", None) else None,
        "reprogramadaPara": entrega.reprogramadaPara.isoformat() if getattr(entrega, "reprogramadaPara", None) else None,
    }


def _ensure_entrega(db: Session, pedido: Pedido, entrega: Entrega | None) -> Entrega:
    if entrega is not None:
        return entrega

    now = datetime.now(timezone.utc)
    entrega = Entrega(
        empresaID=int(pedido.empresaID),
        sucursalID=int(pedido.sucursalID) if pedido.sucursalID is not None else None,
        pedidoID=int(pedido.idPedido),
        estadoEntregaID=domicilio_service.resolve_estado_entrega_id(db, ESTADO_PENDIENTE),
        intentoNumero=1,
        fechaEntregaProgramada=getattr(pedido, "fechaPedido", None),
        createdAt=now,
        updatedAt=now,
    )
    db.add(entrega)
    db.flush()
    return entrega


def _assert_domiciliario_valido(domiciliario: Domiciliario | None, empresa_id: int) -> Domiciliario:
    if not domiciliario or int(domiciliario.empresaID) != int(empresa_id):
        raise _err("DOMICILIARIO_INVALID", "Domiciliario invalido para la empresa", status_code=400)
    if not bool(getattr(domiciliario, "activo", 0)):
        raise _err("DOMICILIARIO_INACTIVO", "El domiciliario seleccionado no esta activo", status_code=400)
    if str(getattr(domiciliario, "cargo", "") or "").strip().lower() != "domiciliario":
        raise _err("DOMICILIARIO_INVALID", "El empleado seleccionado no es domiciliario", status_code=400)
    return domiciliario


def _resolve_pedido_for_regularizacion(
    db: Session,
    *,
    empresa_id: int,
    pedido_ref: int,
    sucursal_id: int | None = None,
) -> Pedido | None:
    base = db.query(Pedido).filter(Pedido.empresaID == int(empresa_id))

    pedido = base.filter(Pedido.idPedido == int(pedido_ref)).with_for_update().first()
    if pedido:
        return pedido

    ref_text = str(pedido_ref).strip()
    codigo_matches = (
        base.filter(func.upper(func.coalesce(Pedido.codigoPedido, "")) == ref_text.upper())
        .with_for_update()
        .all()
    )
    if len(codigo_matches) == 1:
        return codigo_matches[0]
    if len(codigo_matches) > 1:
        raise _err(
            "REGULARIZACION_PEDIDO_AMBIGUO",
            f"El codigo de pedido {pedido_ref} coincide con varios pedidos; envie id_pedido",
            status_code=409,
        )

    numero_query = base.filter(Pedido.numeroPedido == int(pedido_ref))
    if sucursal_id is not None:
        numero_query = numero_query.filter(Pedido.sucursalID == int(sucursal_id))
    numero_matches = numero_query.with_for_update().all()
    if len(numero_matches) == 1:
        return numero_matches[0]
    if len(numero_matches) > 1:
        raise _err(
            "REGULARIZACION_PEDIDO_AMBIGUO",
            f"El numero de pedido {pedido_ref} coincide con varios pedidos; envie id_pedido",
            status_code=409,
        )

    return None


def _assert_transition_path(db: Session, entrega: Entrega, estado_anterior: str):
    if estado_anterior == ESTADO_ENTREGADO:
        return
    if estado_anterior != ESTADO_EN_RUTA:
        domicilio_service.assert_transition_allowed_for_empresa(
            db=db,
            empresa_id=int(entrega.empresaID),
            current=estado_anterior,
            target=ESTADO_ASIGNADO,
        )
    if estado_anterior != ESTADO_EN_RUTA:
        domicilio_service.assert_transition_allowed_for_empresa(
            db=db,
            empresa_id=int(entrega.empresaID),
            current=ESTADO_ASIGNADO,
            target=ESTADO_EN_RUTA,
        )
    domicilio_service.assert_transition_allowed_for_empresa(
        db=db,
        empresa_id=int(entrega.empresaID),
        current=ESTADO_EN_RUTA,
        target=ESTADO_ENTREGADO,
    )


def _regularizar_produccion(
    db: Session,
    pedido: Pedido,
    entrega: Entrega,
    fecha_para_entrega: datetime,
    motivo: str,
    usuario: str,
) -> list[int]:
    producciones = (
        db.query(Produccion)
        .filter(
            Produccion.pedidoID == int(pedido.idPedido),
            Produccion.empresaID == int(pedido.empresaID),
        )
        .with_for_update()
        .all()
    )
    if not producciones:
        produccion_service.asegurar_produccion_desde_pedido_aprobado(
            db=db,
            pedido=pedido,
            dias_anticipacion=0,
            usuario=usuario,
        )
        producciones = (
            db.query(Produccion)
            .filter(
                Produccion.pedidoID == int(pedido.idPedido),
                Produccion.empresaID == int(pedido.empresaID),
            )
            .with_for_update()
            .all()
        )

    para_entrega_id = produccion_service.estado_produccion_id(db, produccion_service.ESTADO_PARA_ENTREGA)
    cancelado = produccion_service.ESTADO_CANCELADO
    changed_ids: list[int] = []
    for produccion in producciones:
        if produccion_service.estado_produccion_norm(produccion.estado, db=db) == cancelado:
            continue
        anterior = int(produccion.floristaID) if produccion.floristaID is not None else None
        produccion.estado = para_entrega_id
        produccion.fechaFinalizacion = fecha_para_entrega
        produccion.updatedAt = datetime.now(timezone.utc)
        if entrega.produccionID is None:
            entrega.produccionID = int(produccion.idProduccion)
        produccion_service.log_historial(
            db=db,
            produccion=produccion,
            florista_anterior_id=anterior,
            florista_nuevo_id=anterior,
            motivo=f"Regularizacion administrativa de entrega historica: {motivo}",
            usuario=usuario,
        )
        changed_ids.append(int(produccion.idProduccion))
    return changed_ids


@router.post("/entregas/regularizar", response_model=RegularizarEntregasResponse)
def regularizar_entregas_historicas(
    payload: RegularizarEntregasRequest,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    _assert_admin(auth)
    assert_same_empresa(auth, int(auth.empresaID))
    motivo = _motivo_regularizacion(payload)
    items = _regularizacion_items(payload)
    if not items:
        raise _err("REGULARIZACION_PEDIDOS_REQUIRED", "Debe enviar al menos un pedido", status_code=422)

    seen: set[int] = set()
    duplicated = [item.pedido_id for item in items if item.pedido_id in seen or seen.add(item.pedido_id)]
    if duplicated:
        raise _err("REGULARIZACION_PEDIDO_DUPLICADO", "No se puede regularizar el mismo pedido dos veces en el lote")

    actor_login = str(getattr(auth, "login", None) or getattr(auth, "nombre", None) or "admin").strip() or "admin"
    execution_at = datetime.now(timezone.utc)
    responses: list[RegularizarEntregaItemResponse] = []

    try:
        domiciliario = _assert_domiciliario_valido(
            db.query(Domiciliario)
            .filter(
                Domiciliario.idDomiciliario == int(payload.domiciliario_id),
                Domiciliario.empresaID == int(auth.empresaID),
            )
            .first(),
            int(auth.empresaID),
        )

        for item in items:
            pedido = _resolve_pedido_for_regularizacion(
                db,
                empresa_id=int(auth.empresaID),
                pedido_ref=int(item.pedido_id),
                sucursal_id=(
                    int(getattr(auth, "sucursalID", None))
                    if getattr(auth, "sucursalID", None) is not None
                    else (
                        int(getattr(domiciliario, "sucursalID", None))
                        if getattr(domiciliario, "sucursalID", None) is not None
                        else None
                    )
                ),
            )
            if not pedido:
                raise _err("PEDIDO_NOT_FOUND", f"Pedido {item.pedido_id} no encontrado", status_code=404)

            entrega_actual = (
                db.query(Entrega)
                .filter(
                    Entrega.pedidoID == int(pedido.idPedido),
                    Entrega.empresaID == int(pedido.empresaID),
                )
                .order_by(Entrega.intentoNumero.desc(), Entrega.idEntrega.desc())
                .with_for_update()
                .first()
            )
            entrega = _ensure_entrega(db, pedido, entrega_actual)

            if entrega.sucursalID is not None and domiciliario.sucursalID is not None:
                if int(entrega.sucursalID) != int(domiciliario.sucursalID):
                    raise _err(
                        "REGULARIZACION_SCOPE_INVALID",
                        f"Domiciliario no pertenece a la sucursal de la entrega del pedido {pedido.idPedido}",
                        status_code=400,
                    )

            fecha_entrega = datetime.combine(payload.fecha_entrega, item.hora_entrega)
            fecha_programada = _fecha_programada(entrega, pedido)
            if fecha_programada is None:
                fecha_programada = fecha_entrega
            fecha_asignacion, fecha_salida = _timeline_for_regularizacion(fecha_programada, fecha_entrega)

            estado_anterior = domicilio_service.estado_norm(entrega.estadoEntregaID)
            snapshot_anterior = _snapshot_entrega(entrega)
            _assert_transition_path(db, entrega, estado_anterior)

            produccion_ids = _regularizar_produccion(
                db=db,
                pedido=pedido,
                entrega=entrega,
                fecha_para_entrega=min(fecha_programada, fecha_asignacion),
                motivo=motivo,
                usuario=actor_login,
            )

            entrega.domiciliarioID = int(domiciliario.idDomiciliario)
            entrega.empleadoID = int(domiciliario.idDomiciliario)
            entrega.estadoEntregaID = domicilio_service.resolve_estado_entrega_id(db, ESTADO_ENTREGADO)
            entrega.fechaAsignacion = fecha_asignacion
            entrega.fechaSalida = fecha_salida
            entrega.fechaEntrega = fecha_entrega
            if entrega.fechaEntregaProgramada is None:
                entrega.fechaEntregaProgramada = fecha_programada
            entrega.motivoNoEntregado = None
            entrega.updatedAt = execution_at
            db.flush()

            snapshot_nuevo = _snapshot_entrega(entrega)
            domicilios_router._audit_domicilio_action(
                db=db,
                auth=auth,
                entrega=entrega,
                accion="REGULARIZACION_ADMINISTRATIVA",
                estado_anterior=estado_anterior,
                estado_nuevo=ESTADO_ENTREGADO,
                extra={
                    "tipo": "regularizacion_administrativa_historica",
                    "pedidoID": int(pedido.idPedido),
                    "domiciliarioID": int(domiciliario.idDomiciliario),
                    "usuarioAdmin": actor_login,
                    "fechaEjecucionRegularizacion": execution_at.isoformat(),
                    "motivoRegularizacion": motivo,
                    "fechasAnteriores": snapshot_anterior,
                    "fechasNuevas": snapshot_nuevo,
                    "produccionIDs": produccion_ids,
                    "flujoGenerado": [
                        {"estado": ESTADO_ASIGNADO, "fecha": fecha_asignacion.isoformat()},
                        {"estado": ESTADO_EN_RUTA, "fecha": fecha_salida.isoformat()},
                        {"estado": ESTADO_ENTREGADO, "fecha": fecha_entrega.isoformat()},
                    ],
                },
            )
            responses.append(
                RegularizarEntregaItemResponse(
                    pedido_id=int(pedido.idPedido),
                    entrega_id=int(entrega.idEntrega),
                    domiciliario_id=int(domiciliario.idDomiciliario),
                    estado_anterior=estado_anterior,
                    estado_nuevo=ESTADO_ENTREGADO,
                    fecha_asignacion=fecha_asignacion,
                    fecha_salida=fecha_salida,
                    fecha_entrega=fecha_entrega,
                )
            )

        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise _err("REGULARIZACION_FAILED", "No fue posible regularizar las entregas", status_code=500) from exc

    return RegularizarEntregasResponse(status="ok", total=len(responses), items=responses)
