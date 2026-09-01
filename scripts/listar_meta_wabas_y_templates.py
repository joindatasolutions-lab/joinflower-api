import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_GRAPH_VERSION = "v25.0"
DEFAULT_TEMPLATE_NAME = "pedido_entregado"


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


def _fetch_all(url: str, token: str) -> tuple[int, list[dict], dict | None]:
    items: list[dict] = []
    while url:
        status, payload = _get(url, token)
        if status >= 400:
            return status, items, payload
        items.extend(payload.get("data") or [])
        url = (payload.get("paging") or {}).get("next")
    return 200, items, None


def _print_error(title: str, status: int, payload: dict | None) -> None:
    print(f"{title}: HTTP {status}")
    if payload:
        print(json.dumps(payload, indent=2, ensure_ascii=False))


def main() -> int:
    token = (
        os.getenv("META_WHATSAPP_ACCESS_TOKEN")
        or os.getenv("META_SYSTEM_USER_TOKEN")
        or os.getenv("WHATSAPP_TOKEN")
    )
    graph_version = os.getenv("META_WHATSAPP_API_VERSION", DEFAULT_GRAPH_VERSION)
    template_name = os.getenv("WHATSAPP_TEMPLATE_NAME", DEFAULT_TEMPLATE_NAME)

    if not token:
        print("Falta META_WHATSAPP_ACCESS_TOKEN o META_SYSTEM_USER_TOKEN.")
        return 1

    base = f"https://graph.facebook.com/{graph_version}"
    business_fields = "id,name"
    waba_fields = "id,name"
    phone_fields = "id,display_phone_number,verified_name,code_verification_status"
    template_fields = "id,name,language,status,category"

    status, businesses, error = _fetch_all(
        f"{base}/me/businesses?{urlencode({'fields': business_fields, 'limit': '100'})}",
        token,
    )
    if status >= 400:
        _print_error("No fue posible listar negocios del token", status, error)
        return 1

    if not businesses:
        print("El token no retorno negocios en /me/businesses.")
        return 0

    print(f"Negocios visibles: {len(businesses)}")
    found_template = False

    for business in businesses:
        business_id = business.get("id")
        business_name = business.get("name")
        print("=" * 90)
        print(f"Business: {business_name} ({business_id})")

        waba_urls = [
            (
                "owned_whatsapp_business_accounts",
                f"{base}/{business_id}/owned_whatsapp_business_accounts?{urlencode({'fields': waba_fields, 'limit': '100'})}",
            ),
            (
                "client_whatsapp_business_accounts",
                f"{base}/{business_id}/client_whatsapp_business_accounts?{urlencode({'fields': waba_fields, 'limit': '100'})}",
            ),
        ]

        seen_wabas: set[str] = set()
        for relation, url in waba_urls:
            status, wabas, error = _fetch_all(url, token)
            if status >= 400:
                _print_error(f"No fue posible listar {relation}", status, error)
                continue

            for waba in wabas:
                waba_id = str(waba.get("id") or "")
                if not waba_id or waba_id in seen_wabas:
                    continue
                seen_wabas.add(waba_id)
                print("-" * 90)
                print(f"WABA: {waba.get('name')} ({waba_id}) via {relation}")

                phone_url = f"{base}/{waba_id}/phone_numbers?{urlencode({'fields': phone_fields, 'limit': '100'})}"
                phone_status, phones, phone_error = _fetch_all(phone_url, token)
                if phone_status >= 400:
                    _print_error("Telefonos", phone_status, phone_error)
                else:
                    print(f"Telefonos: {len(phones)}")
                    for phone in phones:
                        print(
                            f"  - {phone.get('display_phone_number')} "
                            f"id={phone.get('id')} estado={phone.get('code_verification_status')}"
                        )

                template_url = f"{base}/{waba_id}/message_templates?{urlencode({'fields': template_fields, 'limit': '100'})}"
                template_status, templates, template_error = _fetch_all(template_url, token)
                if template_status >= 400:
                    _print_error("Plantillas", template_status, template_error)
                    continue

                print(f"Plantillas: {len(templates)}")
                for template in templates:
                    marker = ""
                    if str(template.get("name") or "") == template_name:
                        marker = "  <-- COINCIDE"
                        found_template = True
                    print(
                        f"  - {template.get('name')} "
                        f"idioma={template.get('language')} "
                        f"estado={template.get('status')} "
                        f"id={template.get('id')}{marker}"
                    )

    print("=" * 90)
    if found_template:
        print(f"Se encontro la plantilla '{template_name}' en al menos una WABA visible.")
    else:
        print(f"No se encontro la plantilla '{template_name}' en los edges de WABA visibles para este token.")
        print("Si el Template ID directo funciona, probablemente esa plantilla no esta asociada al numero usado para enviar.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
