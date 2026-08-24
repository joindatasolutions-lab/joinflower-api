import os
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.models.cliente import Cliente
from app.models.empresa import Empresa
from app.models.entrega import Entrega
from app.models.pedido import Pedido
from app.models.whatsapp_notificacion import WhatsappNotificacion
from app.schemas.domicilios import ESTADO_ENTREGADO
from app.services import domicilio_service, whatsapp_client

logger = get_logger("whatsapp")

CANAL_WHATSAPP = "WHATSAPP"
EVENTO_ORDER_DELIVERED = "ORDER_DELIVERED"

STATUS_PENDING = "PENDING"
STATUS_SENT = "SENT"
STATUS_DELIVERED = "DELIVERED"
STATUS_READ = "READ"
STATUS_FAILED = "FAILED"
STATUS_SKIPPED = "SKIPPED"

TEMPLATE_PEDIDO_ENTREGADO = os.getenv("WHATSAPP_TEMPLATE_PEDIDO_ENTREGADO", "pedido_entregado")
TEMPLATE_IDIOMA = os.getenv("WHATSAPP_TEMPLATE_IDIOMA", "es")
MAX_INTENTOS = int(os.getenv("WHATSAPP_MAX_INTENTOS", "3"))
# intento 2 a los 30s, intento 3 a los 2min, intento 4 (si MAX_INTENTOS lo permite) a los 10min
BACKOFF_SEGUNDOS = [30, 120, 600]


def encolar_notificacion_entregado(db: Session, *, empresa_id: int, pedido_id: int, entrega_id: int) -> None:
    """Crea la notificacion PENDING para este pedido si no existe ya una (idempotente por
    la restriccion UNIQUE de la tabla, no por esta verificacion en Python).

    Debe llamarse DENTRO de la misma transaccion que confirma la entrega, antes del commit,
    para garantizar que la notificacion se cree si y solo si la entrega realmente se confirma.
    Nunca lanza: un fallo aqui no debe romper la confirmacion de entrega.
    """
    try:
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

    # Defensa en profundidad: aunque hoy la unica forma de crear una fila aqui es el gancho
    # dentro de _marcar_entregado_impl (ya validado), se re-verifica contra el estado real
    # de la entrega antes de enviar -- nunca enviar por un pedido que no esta ENTREGADO.
    entrega = (
        db.query(Entrega)
        .filter(Entrega.idEntrega == notificacion.entregaID, Entrega.empresaID == notificacion.empresaID)
        .first()
    )
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

    nombre_empresa = str(empresa.nombreComercial or empresa.nombreEmpresa or "").strip() or "PetalOps"
    nombre_cliente = str(cliente.nombreCompleto or "").strip() or "Cliente"
    numero_pedido = str(getattr(pedido, "numeroPedido", "") or pedido.idPedido)

    notificacion.clienteID = cliente.idCliente
    notificacion.telefonoDestino = telefono
    notificacion.templateName = TEMPLATE_PEDIDO_ENTREGADO
    notificacion.attempts = int(notificacion.attempts or 0) + 1
    db.commit()

    try:
        meta_message_id = whatsapp_client.enviar_plantilla(
            telefono_destino=telefono,
            template_name=TEMPLATE_PEDIDO_ENTREGADO,
            idioma=TEMPLATE_IDIOMA,
            parametros=[nombre_empresa, nombre_cliente, numero_pedido],
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
        "event=ORDER_DELIVERED tenant_id=%s pedido_id=%s cliente_id=%s notification_id=%s "
        "meta_message_id=%s status=SENT telefono=%s",
        notificacion.empresaID, notificacion.pedidoID, cliente.idCliente, notificacion.idNotificacion,
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
