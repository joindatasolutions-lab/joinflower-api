import hashlib
import hmac
import os

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from app.core.logger import get_logger

router = APIRouter(prefix="/webhooks/whatsapp", tags=["webhooks"])
webhooks_logger = get_logger("webhooks.whatsapp")

WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
WHATSAPP_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET", "")


@router.get("", response_class=PlainTextResponse)
def verificar_webhook(
    hub_mode: str = Query("", alias="hub.mode"),
    hub_verify_token: str = Query("", alias="hub.verify_token"),
    hub_challenge: str = Query("", alias="hub.challenge"),
):
    if hub_mode == "subscribe" and WHATSAPP_VERIFY_TOKEN and hmac.compare_digest(hub_verify_token, WHATSAPP_VERIFY_TOKEN):
        webhooks_logger.info("Verificacion de webhook de WhatsApp exitosa")
        return PlainTextResponse(hub_challenge, status_code=200)

    webhooks_logger.warning("Verificacion de webhook de WhatsApp rechazada. hub.mode=%s", hub_mode)
    raise HTTPException(status_code=403, detail="Verificacion fallida")


def _verificar_firma_meta(raw_body: bytes, signature_header: str | None) -> bool:
    if not WHATSAPP_APP_SECRET:
        webhooks_logger.warning(
            "WHATSAPP_APP_SECRET no configurado: se acepta el evento sin verificar firma (solo aceptable en desarrollo)"
        )
        return True
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    esperada = hmac.new(WHATSAPP_APP_SECRET.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    recibida = signature_header.removeprefix("sha256=")
    return hmac.compare_digest(esperada, recibida)


@router.post("")
async def recibir_evento_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(None),
):
    raw_body = await request.body()

    if not _verificar_firma_meta(raw_body, x_hub_signature_256):
        webhooks_logger.warning("Firma invalida en webhook de WhatsApp, evento rechazado")
        raise HTTPException(status_code=401, detail="Firma invalida")

    payload = await request.json()
    webhooks_logger.info("Evento de WhatsApp recibido: object=%s", payload.get("object"))

    # TODO: procesar los eventos reales (mensajes entrantes, confirmaciones de entrega,
    # cambios de estado, etc.) segun lo que se decida hacer con ellos. Por ahora solo se
    # registra y se confirma recepcion -- es lo unico que Meta exige para no reintentar
    # el envio del mismo evento.

    return {"status": "ok"}
