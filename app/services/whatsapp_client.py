import os

import httpx

META_GRAPH_BASE_URL = os.getenv("META_GRAPH_BASE_URL", "https://graph.facebook.com")
META_API_VERSION = os.getenv("META_WHATSAPP_API_VERSION", "v21.0")
META_ACCESS_TOKEN = os.getenv("META_WHATSAPP_ACCESS_TOKEN", "")
META_PHONE_NUMBER_ID = os.getenv("META_WHATSAPP_PHONE_NUMBER_ID", "")

REQUEST_TIMEOUT_SECONDS = 10.0


class WhatsAppTransientError(Exception):
    """Error recuperable: reintentar (429, 5xx, timeout, error de conexion)."""


class WhatsAppPermanentError(Exception):
    """Error no recuperable: no reintentar (4xx de validacion/autorizacion, config invalida)."""

    def __init__(self, message: str, *, error_code: str | None = None):
        super().__init__(message)
        self.error_code = error_code


class WhatsAppNotConfiguredError(WhatsAppPermanentError):
    """Faltan credenciales de Meta -- no se puede enviar todavia."""


def _safe_error_body(response: httpx.Response) -> str:
    try:
        return str(response.json())[:500]
    except Exception:
        return response.text[:500]


def enviar_plantilla(
    *,
    telefono_destino: str,
    template_name: str,
    idioma: str,
    parametros: list[str],
    header_image_url: str | None = None,
) -> str:
    """Envia un mensaje de plantilla (UTILITY) via Meta Cloud API.

    Retorna el meta_message_id (wamid) devuelto por Meta.
    Lanza WhatsAppTransientError (reintentable) o WhatsAppPermanentError (no reintentable).
    """
    if not META_ACCESS_TOKEN or not META_PHONE_NUMBER_ID:
        raise WhatsAppNotConfiguredError(
            "META_WHATSAPP_ACCESS_TOKEN / META_WHATSAPP_PHONE_NUMBER_ID no configurados",
            error_code="NOT_CONFIGURED",
        )

    url = f"{META_GRAPH_BASE_URL}/{META_API_VERSION}/{META_PHONE_NUMBER_ID}/messages"
    template_payload = {
        "name": template_name,
        "language": {"code": idioma},
    }
    components = []
    if header_image_url:
        components.append(
            {
                "type": "header",
                "parameters": [{"type": "image", "image": {"link": header_image_url}}],
            }
        )
    if parametros:
        components.append(
            {
                "type": "body",
                "parameters": [{"type": "text", "text": parametro} for parametro in parametros],
            }
        )
    if components:
        template_payload["components"] = components

    payload = {
        "messaging_product": "whatsapp",
        "to": telefono_destino,
        "type": "template",
        "template": template_payload,
    }
    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
    except httpx.TimeoutException as exc:
        raise WhatsAppTransientError(f"Timeout llamando a Meta: {exc}") from exc
    except httpx.RequestError as exc:
        raise WhatsAppTransientError(f"Error de conexion llamando a Meta: {exc}") from exc

    if response.status_code == 429 or response.status_code >= 500:
        raise WhatsAppTransientError(f"Meta respondio {response.status_code}: {_safe_error_body(response)}")

    if response.status_code >= 400:
        raise WhatsAppPermanentError(
            f"Meta rechazo el envio ({response.status_code}): {_safe_error_body(response)}",
            error_code=str(response.status_code),
        )

    data = response.json()
    mensajes = data.get("messages") or []
    if not mensajes:
        raise WhatsAppPermanentError("Meta respondio 200 sin 'messages' en el cuerpo", error_code="EMPTY_RESPONSE")
    return str(mensajes[0].get("id") or "")
