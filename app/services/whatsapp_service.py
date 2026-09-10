import os
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.models.cliente import Cliente
from app.models.empresa import Empresa
from app.models.entrega import Entrega
from app.models.pedido import Pedido
from app.models.pedidodetalle import PedidoDetalle
from app.models.producto import Producto
from app.models.whatsapp_notificacion import WhatsappNotificacion
from app.schemas.domicilios import ESTADO_ENTREGADO
from app.services import domicilio_service, whatsapp_client

logger = get_logger("whatsapp")

CANAL_WHATSAPP = "WHATSAPP"
EVENTO_ORDER_DELIVERED = "ORDER_DELIVERED"
EVENTO_ORDER_ACCEPTED = "ORDER_ACCEPTED"
MODULE_NOTIFICACIONES_WHATSAPP = "notificaciones_whatsapp"

STATUS_PENDING = "PENDING"
STATUS_SENT = "SENT"
STATUS_DELIVERED = "DELIVERED"
STATUS_READ = "READ"
STATUS_FAILED = "FAILED"
STATUS_SKIPPED = "SKIPPED"

TEMPLATE_PEDIDO_ENTREGADO = os.getenv("WHATSAPP_TEMPLATE_PEDIDO_ENTREGADO", "pedidoentregado")
TEMPLATE_PEDIDO_ACEPTADO = os.getenv("WHATSAPP_TEMPLATE_PEDIDO_ACEPTADO", "pedidos_aceptado")
TEMPLATE_IDIOMA = os.getenv("WHATSAPP_TEMPLATE_IDIOMA", "es_CO")


def _env_int(name: str, default: int, minimum: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or str(raw_value).strip() == "":
        return default
    try:
        value = int(str(raw_value).strip())
    except (TypeError, ValueError):
        logger.warning("Valor invalido para %s=%r. Usando default %s.", name, raw_value, default)
        return default
    if value < minimum:
        logger.warning("Valor fuera de rango para %s=%s. Minimo permitido %s.", name, value, minimum)
        return minimum
    return value


def _env_bool(name: str, default: bool = True) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None or str(raw_value).strip() == "":
        return default
    return str(raw_value).strip().lower() not in {"0", "false", "no", "off"}


MAX_INTENTOS = _env_int("WHATSAPP_MAX_INTENTOS", default=3, minimum=1)
RECONCILIAR_ENTREGAS_ENABLED = _env_bool("WHATSAPP_RECONCILIAR_ENTREGAS_ENABLED", default=True)
RECONCILIAR_ENTREGAS_HORAS = _env_int("WHATSAPP_RECONCILIAR_ENTREGAS_HORAS", default=6, minimum=1)
RECONCILIAR_ENTREGAS_BATCH_SIZE = _env_int("WHATSAPP_RECONCILIAR_ENTREGAS_BATCH_SIZE", default=100, minimum=1)
# intento 2 a los 30s, intento 3 a los 2min, intento 4 (si MAX_INTENTOS lo permite) a los 10min
BACKOFF_SEGUNDOS = [30, 120, 600]
STATUS_PRIORITY = {
    STATUS_PENDING: 0,
    STATUS_SENT: 1,
    STATUS_DELIVERED: 2,
    STATUS_READ: 3,
    STATUS_FAILED: 4,
    STATUS_SKIPPED: 4,
}


def empresa_tiene_notificaciones_whatsapp_activas(db: Session, empresa_id: int) -> bool:
    override = getattr(db, "whatsapp_notifications_enabled", None)
    if override is not None:
        return bool(override)

    row = db.execute(
        text(
            """
            SELECT activo
            FROM petalops.empresa_modulo
            WHERE empresa_id = :empresa_id
              AND modulo = :modulo
            LIMIT 1
            """
        ),
        {
            "empresa_id": int(empresa_id),
            "modulo": MODULE_NOTIFICACIONES_WHATSAPP,
        },
    ).first()
    return bool(row and row[0])


def encolar_notificacion_entregado(db: Session, *, empresa_id: int, pedido_id: int, entrega_id: int) -> None:
    """Crea la notificacion PENDING para este pedido si no existe ya una (idempotente por
    la restriccion UNIQUE de la tabla, no por esta verificacion en Python).

    Debe llamarse DENTRO de la misma transaccion que confirma la entrega, antes del commit,
    para garantizar que la notificacion se cree si y solo si la entrega realmente se confirma.
    Nunca lanza: un fallo aqui no debe romper la confirmacion de entrega.
    """
    try:
        if not empresa_tiene_notificaciones_whatsapp_activas(db, int(empresa_id)):
            logger.info(
                "Notificacion WhatsApp no encolada: modulo inactivo. empresa_id=%s pedido_id=%s entrega_id=%s",
                empresa_id, pedido_id, entrega_id,
            )
            return
        db.execute(
            text(
                """
                INSERT INTO petalops.whatsapp_notificacion
                    (empresa_id, pedido_id, entrega_id, canal, evento, status, attempts, next_attempt_at, created_at)
                VALUES
                    (:empresa_id, :pedido_id, :entrega_id, :canal, :evento, :status, 0, now(), now())
                ON CONFLICT (empresa_id, pedido_id, evento, canal) DO NOTHING
                """
            ),
            {
                "empresa_id": int(empresa_id),
                "pedido_id": int(pedido_id),
                "entrega_id": int(entrega_id),
                "canal": CANAL_WHATSAPP,
                "evento": EVENTO_ORDER_DELIVERED,
                "status": STATUS_PENDING,
            },
        )
    except Exception:
        logger.exception(
            "No fue posible encolar notificacion de WhatsApp. empresa_id=%s pedido_id=%s entrega_id=%s",
            empresa_id, pedido_id, entrega_id,
        )


def encolar_notificacion_pedido_aceptado(db: Session, *, empresa_id: int, pedido_id: int) -> None:
    """Crea la notificacion PENDING cuando un pedido pasa a APROBADO/PAGADO.

    Usa la misma cola de WhatsApp existente e idempotencia por evento para no duplicar
    mensajes si el pedido se intenta aprobar dos veces.
    """
    try:
        if not empresa_tiene_notificaciones_whatsapp_activas(db, int(empresa_id)):
            logger.info(
                "Notificacion WhatsApp de pedido aceptado no encolada: modulo inactivo. empresa_id=%s pedido_id=%s",
                empresa_id, pedido_id,
            )
            return
        entrega_id = db.execute(
            text(
                """
                SELECT id_entrega
                FROM petalops.entrega
                WHERE empresa_id = :empresa_id
                  AND pedido_id = :pedido_id
                ORDER BY intentonumero DESC NULLS LAST, id_entrega DESC
                LIMIT 1
                """
            ),
            {"empresa_id": int(empresa_id), "pedido_id": int(pedido_id)},
        ).scalar()
        db.execute(
            text(
                """
                INSERT INTO petalops.whatsapp_notificacion
                    (empresa_id, pedido_id, entrega_id, canal, evento, status, attempts, next_attempt_at, created_at)
                VALUES
                    (:empresa_id, :pedido_id, :entrega_id, :canal, :evento, :status, 0, now(), now())
                ON CONFLICT (empresa_id, pedido_id, evento, canal) DO NOTHING
                """
            ),
            {
                "empresa_id": int(empresa_id),
                "pedido_id": int(pedido_id),
                "entrega_id": int(entrega_id) if entrega_id is not None else None,
                "canal": CANAL_WHATSAPP,
                "evento": EVENTO_ORDER_ACCEPTED,
                "status": STATUS_PENDING,
            },
        )
    except Exception:
        logger.exception(
            "No fue posible encolar notificacion de pedido aceptado. empresa_id=%s pedido_id=%s",
            empresa_id, pedido_id,
        )


def reconciliar_entregas_entregadas_sin_notificacion(
    db: Session,
    *,
    limite: int = RECONCILIAR_ENTREGAS_BATCH_SIZE,
    horas_atras: int = RECONCILIAR_ENTREGAS_HORAS,
) -> int:
    """Encola entregas ya confirmadas que quedaron sin notificacion.

    Cubre integraciones externas que cambian la entrega a ENTREGADO sin pasar por
    _marcar_entregado_impl. Es idempotente por el UNIQUE (empresa_id, pedido_id, evento, canal)
    y respeta el modulo activo por empresa.
    """
    if not RECONCILIAR_ENTREGAS_ENABLED:
        return 0

    try:
        result = db.execute(
            text(
                """
                INSERT INTO petalops.whatsapp_notificacion
                    (empresa_id, pedido_id, entrega_id, canal, evento, status, attempts, next_attempt_at, created_at)
                SELECT pendientes.empresa_id,
                       pendientes.pedido_id,
                       pendientes.id_entrega,
                       :canal,
                       :evento,
                       :status,
                       0,
                       now(),
                       now()
                FROM (
                    SELECT e.empresa_id, e.pedido_id, e.id_entrega
                    FROM petalops.entrega e
                    JOIN petalops.estado_entrega ee
                      ON ee.id_estado_entrega = e.estadoentregaid
                    JOIN petalops.empresa_modulo em
                      ON em.empresa_id = e.empresa_id
                     AND em.modulo = :modulo
                     AND coalesce(em.activo, 0) = 1
                    WHERE e.pedido_id IS NOT NULL
                      AND lower(coalesce(ee.codigo, ee.nombre, '')) = :estado_entregado
                      AND greatest(
                            coalesce(e.updatedat, timestamp '1970-01-01'),
                            coalesce(e.fechaentrega, timestamp '1970-01-01')
                          ) >= now() - (CAST(:horas_atras AS integer) * interval '1 hour')
                      AND NOT EXISTS (
                          SELECT 1
                          FROM petalops.whatsapp_notificacion wn
                          WHERE wn.empresa_id = e.empresa_id
                            AND wn.pedido_id = e.pedido_id
                            AND wn.evento = :evento
                            AND wn.canal = :canal
                      )
                    ORDER BY greatest(
                               coalesce(e.updatedat, timestamp '1970-01-01'),
                               coalesce(e.fechaentrega, timestamp '1970-01-01')
                             ) DESC,
                             e.id_entrega DESC
                    LIMIT :limite
                ) pendientes
                ON CONFLICT (empresa_id, pedido_id, evento, canal) DO NOTHING
                RETURNING id_notificacion
                """
            ),
            {
                "canal": CANAL_WHATSAPP,
                "evento": EVENTO_ORDER_DELIVERED,
                "status": STATUS_PENDING,
                "modulo": MODULE_NOTIFICACIONES_WHATSAPP,
                "estado_entregado": ESTADO_ENTREGADO.lower(),
                "horas_atras": int(horas_atras),
                "limite": int(limite),
            },
        )
        insertadas = len(result.fetchall())
        if insertadas:
            logger.info(
                "Reconciliacion WhatsApp encolo entregas entregadas sin notificacion. total=%s horas_atras=%s",
                insertadas, horas_atras,
            )
        return insertadas
    except Exception:
        db.rollback()
        logger.exception("No fue posible reconciliar entregas entregadas sin notificacion de WhatsApp")
        return 0


def _enmascarar_telefono(telefono: str | None) -> str:
    telefono = str(telefono or "")
    if len(telefono) <= 4:
        return "*" * len(telefono)
    return "*" * (len(telefono) - 4) + telefono[-4:]


def _normalizar_telefono_whatsapp(cliente: Cliente) -> str | None:
    """Devuelve el telefono en el formato que exige Meta (solo digitos, con indicativo de
    pais, sin '+'), o None si no hay un telefono valido. Nunca lanza excepcion."""
    crudo = str(getattr(cliente, "telefonoCompleto", "") or "").strip()
    if not crudo:
        indicativo = str(getattr(cliente, "indicativo", "") or "").strip()
        telefono = str(getattr(cliente, "telefono", "") or "").strip()
        crudo = f"{indicativo}{telefono}"

    solo_digitos = "".join(ch for ch in crudo if ch.isdigit())
    if not solo_digitos:
        return None

    # Numero colombiano sin indicativo (10 digitos, celular empieza en 3): anteponer 57.
    if len(solo_digitos) == 10 and solo_digitos.startswith("3"):
        solo_digitos = f"57{solo_digitos}"

    # Longitud razonable para un numero internacional (E.164: 8 a 15 digitos).
    if len(solo_digitos) < 10 or len(solo_digitos) > 15:
        return None

    return solo_digitos


def _marcar(db: Session, notificacion: WhatsappNotificacion, **campos) -> None:
    for nombre, valor in campos.items():
        setattr(notificacion, nombre, valor)
    db.commit()


def _datetime_from_meta_timestamp(timestamp: Any) -> datetime:
    try:
        return datetime.utcfromtimestamp(int(timestamp))
    except (TypeError, ValueError, OSError, OverflowError):
        return datetime.utcnow()


def _error_message_from_meta_status(status_payload: dict[str, Any]) -> tuple[str | None, str | None]:
    errors = status_payload.get("errors") or []
    if not errors:
        return None, None

    error = errors[0] if isinstance(errors[0], dict) else {}
    code = str(error.get("code") or error.get("error_code") or "META_STATUS_FAILED")
    parts = [
        str(error.get("title") or "").strip(),
        str(error.get("message") or "").strip(),
    ]
    error_data = error.get("error_data") if isinstance(error.get("error_data"), dict) else {}
    details = str(error_data.get("details") or "").strip()
    if details:
        parts.append(details)
    message = " | ".join(part for part in parts if part) or "Meta reporto fallo en la entrega"
    return code[:60], message[:500]


def _mantener_estado_mas_avanzado(actual: str | None, nuevo: str) -> str:
    actual_normalizado = str(actual or "").upper()
    if STATUS_PRIORITY.get(actual_normalizado, -1) > STATUS_PRIORITY.get(nuevo, -1):
        return actual_normalizado
    return nuevo


def procesar_estado_webhook_meta(db: Session, status_payload: dict[str, Any]) -> bool:
    """Actualiza una notificacion local con el estado asincrono enviado por Meta.

    Retorna True cuando encontro una notificacion local por meta_message_id. Retorna False
    si el webhook corresponde a un mensaje que este backend no conoce.
    """
    meta_message_id = str(status_payload.get("id") or "").strip()
    estado_meta = str(status_payload.get("status") or "").strip().lower()
    if not meta_message_id or not estado_meta:
        return False

    notificacion = (
        db.query(WhatsappNotificacion)
        .filter(WhatsappNotificacion.metaMessageId == meta_message_id)
        .first()
    )
    if not notificacion:
        logger.warning("Webhook WhatsApp sin notificacion local. meta_message_id=%s estado=%s", meta_message_id, estado_meta)
        return False

    momento = _datetime_from_meta_timestamp(status_payload.get("timestamp"))
    if estado_meta == "sent":
        notificacion.status = _mantener_estado_mas_avanzado(notificacion.status, STATUS_SENT)
        notificacion.sentAt = notificacion.sentAt or momento
    elif estado_meta == "delivered":
        notificacion.status = _mantener_estado_mas_avanzado(notificacion.status, STATUS_DELIVERED)
        notificacion.sentAt = notificacion.sentAt or momento
        notificacion.deliveredAt = notificacion.deliveredAt or momento
    elif estado_meta == "read":
        notificacion.status = _mantener_estado_mas_avanzado(notificacion.status, STATUS_READ)
        notificacion.sentAt = notificacion.sentAt or momento
        notificacion.deliveredAt = notificacion.deliveredAt or momento
        notificacion.readAt = notificacion.readAt or momento
    elif estado_meta == "failed":
        error_code, error_message = _error_message_from_meta_status(status_payload)
        notificacion.status = STATUS_FAILED
        notificacion.failedAt = momento
        notificacion.errorCode = error_code or "META_STATUS_FAILED"
        notificacion.errorMessage = error_message or "Meta reporto fallo en la entrega"
    else:
        logger.info("Estado WhatsApp ignorado. meta_message_id=%s estado=%s", meta_message_id, estado_meta)
        return False

    db.commit()
    logger.info(
        "Webhook WhatsApp aplicado. notification_id=%s meta_message_id=%s status=%s",
        notificacion.idNotificacion, meta_message_id, notificacion.status,
    )
    return True


def procesar_webhook_meta(db: Session, payload: dict[str, Any]) -> dict[str, int]:
    recibidos = 0
    aplicados = 0
    desconocidos = 0

    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") if isinstance(change, dict) else {}
            if not isinstance(value, dict):
                continue
            for status_payload in value.get("statuses") or []:
                if not isinstance(status_payload, dict):
                    continue
                recibidos += 1
                if procesar_estado_webhook_meta(db, status_payload):
                    aplicados += 1
                else:
                    desconocidos += 1

    return {
        "statuses_received": recibidos,
        "statuses_applied": aplicados,
        "statuses_unknown": desconocidos,
    }


def _nombre_empresa(empresa: Empresa) -> str:
    return str(empresa.nombreComercial or empresa.nombreEmpresa or "").strip() or "PetalOps"


def _logo_empresa_url(db: Session, empresa_id: int) -> str | None:
    try:
        row = db.execute(
            text("SELECT logo_url FROM petalops.empresa WHERE id_empresa = :empresa_id"),
            {"empresa_id": int(empresa_id)},
        ).first()
        logo_url = str(row[0] or "").strip() if row and row[0] else ""
        return logo_url if logo_url.startswith("https://") else None
    except Exception:
        logger.warning("No fue posible consultar logo_url para WhatsApp. empresa_id=%s", empresa_id, exc_info=True)
        return None


def _estado_pedido_nombre(db: Session, estado_pedido_id: int | None) -> str:
    if estado_pedido_id is None:
        return ""
    try:
        row = db.execute(
            text(
                """
                SELECT UPPER(TRIM(nombre_estado))
                FROM petalops.estado_pedido
                WHERE id_estado_pedido = :estado_pedido_id
                LIMIT 1
                """
            ),
            {"estado_pedido_id": int(estado_pedido_id)},
        ).first()
        return str(row[0] or "").strip().upper() if row else ""
    except Exception:
        logger.warning("No fue posible consultar estado del pedido para WhatsApp. estado_pedido_id=%s", estado_pedido_id, exc_info=True)
        return ""


def _cantidad_texto(value: Any) -> str:
    cantidad = Decimal(str(value or 0))
    if cantidad == cantidad.to_integral_value():
        return str(int(cantidad))
    return f"{cantidad.normalize():f}"


def _valor_texto(value: Any) -> str:
    valor = Decimal(str(value or 0)).quantize(Decimal("1"))
    return str(int(valor))


def _fecha_texto(value: datetime | None) -> str:
    if not value:
        return "No especificada"
    if hasattr(value, "date"):
        return value.date().isoformat()
    return str(value)


def _entrega_para_pedido(db: Session, pedido: Pedido, entrega_id: int | None = None) -> Entrega | None:
    query = db.query(Entrega).filter(
        Entrega.pedidoID == int(pedido.idPedido),
        Entrega.empresaID == int(pedido.empresaID),
    )
    if entrega_id is not None:
        query = query.filter(Entrega.idEntrega == int(entrega_id))
    return query.order_by(Entrega.intentoNumero.desc(), Entrega.idEntrega.desc()).first()


def _producto_resumen_pedido(db: Session, pedido: Pedido) -> str:
    rows = (
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
    productos = []
    for detalle, producto in rows:
        nombre = str(getattr(producto, "nombreProducto", "") or "").strip()
        if not nombre:
            nombre = str(getattr(detalle, "observacionesPersonalizados", "") or "").strip()
        if not nombre:
            nombre = "Producto personalizado"
        productos.append(f"{_cantidad_texto(detalle.cantidad)} x {nombre}")
    return ", ".join(productos) if productos else "Pedido personalizado"


def _parametros_pedido_aceptado(db: Session, *, pedido: Pedido, cliente: Cliente, empresa: Empresa) -> tuple[list[str], str | None]:
    entrega = _entrega_para_pedido(db, pedido)
    fecha_entrega = (
        getattr(entrega, "reprogramadaPara", None)
        or getattr(entrega, "fechaEntregaProgramada", None)
        or getattr(entrega, "fechaEntrega", None)
        or getattr(pedido, "fechaPedido", None)
    )
    direccion = str(getattr(entrega, "direccion", "") or "").strip() if entrega else ""
    if not direccion:
        direccion = "Recoger en tienda"
    numero_pedido = str(getattr(pedido, "numeroPedido", "") or getattr(pedido, "idPedido", ""))
    parametros = [
        str(getattr(cliente, "nombreCompleto", "") or "Cliente").strip() or "Cliente",
        numero_pedido,
        _producto_resumen_pedido(db, pedido),
        _fecha_texto(fecha_entrega),
        _valor_texto(getattr(pedido, "totalNeto", None) or getattr(pedido, "totalBruto", None)),
        direccion,
        _nombre_empresa(empresa),
    ]
    return parametros, _logo_empresa_url(db, int(pedido.empresaID))


def _procesar_una(db: Session, notificacion: WhatsappNotificacion) -> None:
    ahora = datetime.utcnow()

    pedido = (
        db.query(Pedido)
        .filter(Pedido.idPedido == notificacion.pedidoID, Pedido.empresaID == notificacion.empresaID)
        .first()
    )
    if pedido is None:
        logger.warning(
            "Pedido no encontrado en la empresa esperada. notificacion_id=%s empresa_id=%s pedido_id=%s",
            notificacion.idNotificacion, notificacion.empresaID, notificacion.pedidoID,
        )
        _marcar(
            db, notificacion, status=STATUS_FAILED, errorCode="PEDIDO_NOT_FOUND",
            errorMessage="Pedido no encontrado en la empresa esperada", failedAt=ahora,
        )
        return

    cliente = (
        db.query(Cliente)
        .filter(Cliente.idCliente == pedido.clienteID, Cliente.empresaID == notificacion.empresaID)
        .first()
    )
    if cliente is None:
        logger.error(
            "SECURITY_TENANT_MISMATCH: cliente del pedido no pertenece a la empresa esperada. "
            "notificacion_id=%s empresa_id=%s pedido_id=%s cliente_id=%s",
            notificacion.idNotificacion, notificacion.empresaID, notificacion.pedidoID, pedido.clienteID,
        )
        _marcar(
            db, notificacion, status=STATUS_FAILED, errorCode="SECURITY_TENANT_MISMATCH",
            errorMessage="Cliente no pertenece a la empresa del pedido", failedAt=ahora,
        )
        return

    empresa = db.query(Empresa).filter(Empresa.idEmpresa == notificacion.empresaID).first()
    if empresa is None:
        _marcar(
            db, notificacion, status=STATUS_FAILED, errorCode="EMPRESA_NOT_FOUND",
            errorMessage="Empresa no encontrada", failedAt=ahora,
        )
        return

    if not empresa_tiene_notificaciones_whatsapp_activas(db, int(notificacion.empresaID)):
        logger.info(
            "Notificacion WhatsApp omitida: modulo inactivo. notificacion_id=%s empresa_id=%s pedido_id=%s",
            notificacion.idNotificacion, notificacion.empresaID, notificacion.pedidoID,
        )
        _marcar(
            db, notificacion, status=STATUS_SKIPPED, errorCode="WHATSAPP_MODULE_DISABLED",
            errorMessage="Modulo notificaciones_whatsapp inactivo para la empresa", failedAt=ahora,
        )
        return

    # Verificacion final explicita (no assert): defensa en profundidad. Ver
    # pendientes/Mejoras/whatsapp-notificacion-entregado-decisiones.md -- ni pedido, ni
    # entrega, ni cliente tienen FK real en la base de datos, esta verificacion en codigo
    # es la unica proteccion real contra un cruce de datos entre empresas.
    if not (int(pedido.empresaID) == int(cliente.empresaID) == int(empresa.idEmpresa) == int(notificacion.empresaID)):
        logger.error(
            "SECURITY_TENANT_MISMATCH detectado en verificacion final. notificacion_id=%s "
            "pedido.empresa_id=%s cliente.empresa_id=%s empresa.id=%s",
            notificacion.idNotificacion, pedido.empresaID, cliente.empresaID, empresa.idEmpresa,
        )
        _marcar(
            db, notificacion, status=STATUS_FAILED, errorCode="SECURITY_TENANT_MISMATCH",
            errorMessage="Verificacion final de aislamiento entre empresas fallida", failedAt=ahora,
        )
        return

    evento = str(notificacion.evento or EVENTO_ORDER_DELIVERED).strip().upper()
    template_name = TEMPLATE_PEDIDO_ENTREGADO
    parametros: list[str] = []
    header_image_url = None

    if evento == EVENTO_ORDER_ACCEPTED:
        estado_pedido = _estado_pedido_nombre(db, getattr(pedido, "estadoPedidoID", None))
        if estado_pedido not in {"APROBADO", "PAGADO"}:
            logger.warning(
                "Pedido ya no esta aprobado, no se envia aceptacion. notificacion_id=%s pedido_id=%s estado=%s",
                notificacion.idNotificacion, notificacion.pedidoID, estado_pedido,
            )
            _marcar(
                db, notificacion, status=STATUS_SKIPPED, errorCode="PEDIDO_NOT_APPROVED",
                errorMessage="El pedido ya no esta en estado APROBADO/PAGADO", failedAt=ahora,
            )
            return
        template_name = TEMPLATE_PEDIDO_ACEPTADO
        parametros, header_image_url = _parametros_pedido_aceptado(
            db,
            pedido=pedido,
            cliente=cliente,
            empresa=empresa,
        )
    elif evento == EVENTO_ORDER_DELIVERED:
        # Defensa en profundidad: se re-verifica contra el estado real de la entrega
        # antes de enviar -- nunca enviar por un pedido que no esta ENTREGADO.
        entrega = _entrega_para_pedido(db, pedido, int(notificacion.entregaID) if notificacion.entregaID else None)
        if entrega is None or domicilio_service.estado_norm(entrega.estadoEntregaID) != ESTADO_ENTREGADO:
            logger.warning(
                "La entrega asociada no esta en estado ENTREGADO, no se envia. notificacion_id=%s entrega_id=%s",
                notificacion.idNotificacion, notificacion.entregaID,
            )
            _marcar(
                db, notificacion, status=STATUS_SKIPPED, errorCode="ENTREGA_NOT_DELIVERED",
                errorMessage="La entrega asociada no esta en estado ENTREGADO", failedAt=ahora,
            )
            return
    else:
        logger.warning(
            "Evento WhatsApp no soportado. notificacion_id=%s evento=%s",
            notificacion.idNotificacion, evento,
        )
        _marcar(
            db, notificacion, status=STATUS_SKIPPED, errorCode="UNSUPPORTED_EVENT",
            errorMessage="Evento de WhatsApp no soportado", failedAt=ahora,
        )
        return

    telefono = _normalizar_telefono_whatsapp(cliente)
    if not telefono:
        logger.info(
            "SKIPPED_INVALID_PHONE. notificacion_id=%s empresa_id=%s pedido_id=%s cliente_id=%s",
            notificacion.idNotificacion, notificacion.empresaID, notificacion.pedidoID, cliente.idCliente,
        )
        _marcar(
            db, notificacion, status=STATUS_SKIPPED, errorCode="SKIPPED_INVALID_PHONE",
            errorMessage="Telefono del cliente invalido o ausente", failedAt=ahora, clienteID=cliente.idCliente,
        )
        return

    notificacion.clienteID = cliente.idCliente
    notificacion.telefonoDestino = telefono
    notificacion.templateName = template_name
    notificacion.attempts = int(notificacion.attempts or 0) + 1
    db.commit()

    try:
        meta_message_id = whatsapp_client.enviar_plantilla(
            telefono_destino=telefono,
            template_name=template_name,
            idioma=TEMPLATE_IDIOMA,
            parametros=parametros,
            header_image_url=header_image_url,
        )
    except whatsapp_client.WhatsAppTransientError as exc:
        logger.warning(
            "Fallo transitorio enviando WhatsApp, se reintentara. notificacion_id=%s intento=%s error=%s",
            notificacion.idNotificacion, notificacion.attempts, exc,
        )
        if notificacion.attempts >= MAX_INTENTOS:
            _marcar(
                db, notificacion, status=STATUS_FAILED, errorCode="MAX_RETRIES_EXCEEDED",
                errorMessage=str(exc)[:500], failedAt=ahora,
            )
        else:
            espera = BACKOFF_SEGUNDOS[min(notificacion.attempts - 1, len(BACKOFF_SEGUNDOS) - 1)]
            _marcar(
                db, notificacion, status=STATUS_PENDING, errorCode="TRANSIENT",
                errorMessage=str(exc)[:500], nextAttemptAt=ahora + timedelta(seconds=espera),
            )
        return
    except whatsapp_client.WhatsAppPermanentError as exc:
        logger.error(
            "Fallo permanente enviando WhatsApp, no se reintenta. notificacion_id=%s error=%s",
            notificacion.idNotificacion, exc,
        )
        _marcar(
            db, notificacion, status=STATUS_FAILED, errorCode=(getattr(exc, "error_code", None) or "PERMANENT_ERROR"),
            errorMessage=str(exc)[:500], failedAt=ahora,
        )
        return
    except Exception as exc:  # nunca debe tumbar el job completo por un error inesperado
        logger.exception("Error inesperado enviando WhatsApp. notificacion_id=%s", notificacion.idNotificacion)
        _marcar(
            db, notificacion, status=STATUS_FAILED, errorCode="UNEXPECTED_ERROR",
            errorMessage=str(exc)[:500], failedAt=ahora,
        )
        return

    logger.info(
        "event=%s tenant_id=%s pedido_id=%s cliente_id=%s notification_id=%s "
        "meta_message_id=%s status=SENT telefono=%s",
        evento, notificacion.empresaID, notificacion.pedidoID, cliente.idCliente, notificacion.idNotificacion,
        meta_message_id, _enmascarar_telefono(telefono),
    )
    _marcar(
        db, notificacion, status=STATUS_SENT, metaMessageId=meta_message_id, sentAt=ahora,
        errorCode=None, errorMessage=None,
    )


def procesar_notificaciones_pendientes(db: Session, *, limite: int = 20) -> int:
    """Procesa hasta `limite` notificaciones PENDING cuyo turno ya llego (primer intento o
    reintento con backoff cumplido). Retorna cuantas se procesaron.

    Debe llamarse unicamente desde el job de fondo (app/jobs/whatsapp_dispatch_job.py),
    nunca desde el ciclo de una peticion HTTP -- el envio a Meta no debe bloquear ninguna
    respuesta al usuario.
    """
    reconciliar_entregas_entregadas_sin_notificacion(db, limite=RECONCILIAR_ENTREGAS_BATCH_SIZE)

    ahora = datetime.utcnow()
    pendientes = (
        db.query(WhatsappNotificacion)
        .filter(
            WhatsappNotificacion.status == STATUS_PENDING,
            (WhatsappNotificacion.nextAttemptAt.is_(None)) | (WhatsappNotificacion.nextAttemptAt <= ahora),
        )
        .order_by(WhatsappNotificacion.createdAt.asc())
        .limit(limite)
        .all()
    )
    for notificacion in pendientes:
        try:
            _procesar_una(db, notificacion)
        except Exception:
            db.rollback()
            logger.exception(
                "Error procesando notificacion de WhatsApp. notificacion_id=%s", notificacion.idNotificacion
            )
    return len(pendientes)
