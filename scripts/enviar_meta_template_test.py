import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_GRAPH_VERSION = "v25.0"
DEFAULT_PHONE_NUMBER_ID = "1307085025819477"
DEFAULT_TO = "573007252222"


def _normalize_phone(value: str) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) == 10 and digits.startswith("3"):
        return f"57{digits}"
    return digits


def _template_parameters(raw: str | None) -> list[dict]:
    parts = [part.strip() for part in str(raw or "").split("|") if part.strip()]
    return [{"type": "text", "text": part} for part in parts]


def main() -> int:
    token = (
        os.getenv("META_WHATSAPP_ACCESS_TOKEN")
        or os.getenv("META_SYSTEM_USER_TOKEN")
        or os.getenv("WHATSAPP_TOKEN")
    )
    phone_number_id = os.getenv("META_WHATSAPP_PHONE_NUMBER_ID") or os.getenv(
        "META_PHONE_NUMBER_ID",
        DEFAULT_PHONE_NUMBER_ID,
    )
    graph_version = os.getenv("META_WHATSAPP_API_VERSION", DEFAULT_GRAPH_VERSION)
    template_name = os.getenv("WHATSAPP_TEMPLATE_NAME") or os.getenv(
        "WHATSAPP_TEMPLATE_PEDIDO_ENTREGADO",
        "pedidoentregado",
    )
    language = os.getenv("WHATSAPP_TEMPLATE_IDIOMA", "es_CO")
    to = _normalize_phone(os.getenv("WHATSAPP_TEST_TO", DEFAULT_TO))
    parameters = _template_parameters(os.getenv("WHATSAPP_TEMPLATE_PARAMS"))

    if not token:
        print("Falta META_WHATSAPP_ACCESS_TOKEN o META_SYSTEM_USER_TOKEN.")
        print("Ejemplo PowerShell:")
        print('$env:META_WHATSAPP_ACCESS_TOKEN="TU_TOKEN_DEL_SYSTEM_USER"')
        return 1

    if not phone_number_id:
        print("Falta META_WHATSAPP_PHONE_NUMBER_ID.")
        return 1

    if not template_name:
        print("Falta WHATSAPP_TEMPLATE_NAME.")
        return 1

    if len(to) < 10 or len(to) > 15:
        print("WHATSAPP_TEST_TO no parece un telefono valido en formato internacional.")
        print("Ejemplo Colombia: 573007252222")
        return 1

    template = {
        "name": template_name,
        "language": {"code": language},
    }
    if parameters:
        template["components"] = [
            {
                "type": "body",
                "parameters": parameters,
            }
        ]

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": template,
    }

    url = f"https://graph.facebook.com/{graph_version}/{phone_number_id}/messages"
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    print(f"Enviando plantilla '{template_name}' a {to} desde Phone Number ID {phone_number_id}.")
    print("No se imprimen token ni PIN.")

    try:
        with urlopen(request, timeout=20) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"Meta respondio HTTP {exc.code}.")
        try:
            print(json.dumps(json.loads(body), indent=2, ensure_ascii=False))
        except json.JSONDecodeError:
            print(body)
        return 1
    except URLError as exc:
        print(f"No fue posible conectar con Meta: {exc.reason}")
        return 1
    except TimeoutError:
        print("La solicitud a Meta supero el tiempo de espera.")
        return 1

    print(json.dumps(response_payload, indent=2, ensure_ascii=False))
    messages = response_payload.get("messages") or []
    if messages:
        print(f"Meta Message ID: {messages[0].get('id')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
