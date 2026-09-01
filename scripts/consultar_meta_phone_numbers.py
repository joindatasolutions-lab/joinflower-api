import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


GRAPH_VERSION = "v25.0"
DEFAULT_WABA_ID = "1442546971115411"


def main() -> int:
    token = os.getenv("META_SYSTEM_USER_TOKEN") or os.getenv("WHATSAPP_TOKEN")
    waba_id = os.getenv("META_WABA_ID", DEFAULT_WABA_ID)

    if not token:
        print("Falta la variable de entorno META_SYSTEM_USER_TOKEN.")
        print("Ejemplo PowerShell:")
        print('$env:META_SYSTEM_USER_TOKEN="TU_TOKEN_DEL_SYSTEM_USER"')
        return 1

    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{waba_id}/phone_numbers"
    request = Request(url, headers={"Authorization": f"Bearer {token}"}, method="GET")

    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
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

    numbers = payload.get("data") or []
    if not numbers:
        print("La WABA no retorno numeros asociados para este token.")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    print(f"Numeros encontrados para WABA {waba_id}:")
    for item in numbers:
        print("-" * 60)
        print(f"Phone Number ID: {item.get('id')}")
        print(f"Nombre verificado: {item.get('verified_name')}")
        print(f"Numero visible: {item.get('display_phone_number')}")
        if item.get("quality_rating"):
            print(f"Calidad: {item.get('quality_rating')}")
        if item.get("code_verification_status"):
            print(f"Verificacion: {item.get('code_verification_status')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
