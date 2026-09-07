import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_GRAPH_VERSION = "v25.0"
DEFAULT_WABA_ID = "1442546971115411"
DEFAULT_PHONE_NUMBER_ID = "1307085025819477"
DEFAULT_TEMPLATE_NAME = "pedidoentregado"
DEFAULT_TEMPLATE_ID = "1843333309983728"


def _get(url: str, token: str) -> tuple[int, dict]:
    request = Request(url, headers={"Authorization": f"Bearer {token}"}, method="GET")
    try:
        with urlopen(request, timeout=20) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, {"raw": body}


def _print_json(title: str, status: int, payload: dict) -> None:
    print("=" * 80)
    print(f"{title} HTTP {status}")
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def main() -> int:
    token = (
        os.getenv("META_WHATSAPP_ACCESS_TOKEN")
        or os.getenv("META_SYSTEM_USER_TOKEN")
        or os.getenv("WHATSAPP_TOKEN")
    )
    graph_version = os.getenv("META_WHATSAPP_API_VERSION", DEFAULT_GRAPH_VERSION)
    waba_id = os.getenv("META_WABA_ID", DEFAULT_WABA_ID)
    phone_number_id = os.getenv("META_PHONE_NUMBER_ID") or os.getenv(
        "META_WHATSAPP_PHONE_NUMBER_ID",
        DEFAULT_PHONE_NUMBER_ID,
    )
    template_name = os.getenv("WHATSAPP_TEMPLATE_NAME", DEFAULT_TEMPLATE_NAME)
    template_id = os.getenv("META_TEMPLATE_ID", DEFAULT_TEMPLATE_ID)

    if not token:
        print("Falta META_WHATSAPP_ACCESS_TOKEN o META_SYSTEM_USER_TOKEN.")
        return 1

    base = f"https://graph.facebook.com/{graph_version}"

    checks = [
        (
            "1. Phone Number ID",
            f"{base}/{phone_number_id}?{urlencode({'fields': 'id,display_phone_number,verified_name,quality_rating,code_verification_status,platform_type,whatsapp_business_account'})}",
        ),
        (
            "2. Numeros visibles en la WABA",
            f"{base}/{waba_id}/phone_numbers?{urlencode({'fields': 'id,display_phone_number,verified_name,quality_rating,code_verification_status', 'limit': '100'})}",
        ),
        (
            "3. Plantillas visibles en la WABA",
            f"{base}/{waba_id}/message_templates?{urlencode({'fields': 'id,name,language,status,category,components', 'limit': '100'})}",
        ),
        (
            "4. Buscar plantilla por nombre en la WABA",
            f"{base}/{waba_id}/message_templates?{urlencode({'name': template_name, 'fields': 'id,name,language,status,category,components', 'limit': '20'})}",
        ),
        (
            "5. Template ID directo",
            f"{base}/{template_id}?{urlencode({'fields': 'id,name,language,status,category,components'})}",
        ),
    ]

    exit_code = 0
    for title, url in checks:
        try:
            status, payload = _get(url, token)
        except URLError as exc:
            print(f"No fue posible conectar con Meta: {exc.reason}")
            return 1
        except TimeoutError:
            print("La solicitud a Meta supero el tiempo de espera.")
            return 1

        _print_json(title, status, payload)
        if status >= 400:
            exit_code = 1

    print("=" * 80)
    print("Lectura rapida:")
    print("- Si el punto 1 muestra otra WABA distinta, estas enviando desde un numero de otra cuenta.")
    print("- Si el punto 2 no incluye el Phone Number ID, el numero no pertenece a esa WABA.")
    print("- Si el punto 3 o 4 no muestra la plantilla, el token no la ve o esta en otra WABA.")
    print("- Si el punto 5 funciona pero el punto 4 no, el Template ID existe pero no cuelga de esa WABA/token.")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
