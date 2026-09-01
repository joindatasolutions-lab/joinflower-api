import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


GRAPH_VERSION = "v25.0"
DEFAULT_PHONE_NUMBER_ID = "1307085025819477"


def _validate_pin(pin: str) -> bool:
    return len(pin) == 6 and pin.isdigit()


def main() -> int:
    token = os.getenv("META_SYSTEM_USER_TOKEN") or os.getenv("WHATSAPP_TOKEN")
    pin = os.getenv("META_PHONE_PIN") or os.getenv("WHATSAPP_PHONE_PIN")
    phone_number_id = os.getenv("META_PHONE_NUMBER_ID", DEFAULT_PHONE_NUMBER_ID)

    if not token:
        print("Falta la variable de entorno META_SYSTEM_USER_TOKEN.")
        print("Ejemplo PowerShell:")
        print('$env:META_SYSTEM_USER_TOKEN="TU_TOKEN_DEL_SYSTEM_USER"')
        return 1

    if not pin:
        print("Falta la variable de entorno META_PHONE_PIN.")
        print("Debe ser un PIN definido por ti, de 6 digitos. No es el codigo SMS.")
        print("Ejemplo PowerShell:")
        print('$env:META_PHONE_PIN="123456"')
        return 1

    if not _validate_pin(pin):
        print("META_PHONE_PIN debe tener exactamente 6 digitos numericos.")
        return 1

    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{phone_number_id}/register"
    payload = {
        "messaging_product": "whatsapp",
        "pin": pin,
    }
    body = json.dumps(payload).encode("utf-8")

    request = Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=20) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"Meta respondio HTTP {exc.code}.")
        try:
            error_payload = json.loads(body)
            print(json.dumps(error_payload, indent=2, ensure_ascii=False))
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
    if response_payload.get("success") is True:
        print(f"Phone Number ID {phone_number_id} registrado correctamente.")
        return 0

    print("Meta respondio, pero no retorno success=true.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
