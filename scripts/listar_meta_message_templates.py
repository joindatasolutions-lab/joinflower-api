import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_GRAPH_VERSION = "v25.0"
DEFAULT_WABA_ID = "1442546971115411"


def _fetch(url: str, token: str) -> dict:
    request = Request(
        url,
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _body_variable_count(components: list[dict]) -> int:
    for component in components or []:
        if str(component.get("type") or "").upper() != "BODY":
            continue
        text = str(component.get("text") or "")
        return max(text.count("{{"), 0)
    return 0


def main() -> int:
    token = (
        os.getenv("META_WHATSAPP_ACCESS_TOKEN")
        or os.getenv("META_SYSTEM_USER_TOKEN")
        or os.getenv("WHATSAPP_TOKEN")
    )
    waba_id = os.getenv("META_WABA_ID", DEFAULT_WABA_ID)
    graph_version = os.getenv("META_WHATSAPP_API_VERSION", DEFAULT_GRAPH_VERSION)

    if not token:
        print("Falta META_WHATSAPP_ACCESS_TOKEN o META_SYSTEM_USER_TOKEN.")
        print("Ejemplo PowerShell:")
        print('$env:META_WHATSAPP_ACCESS_TOKEN="TU_TOKEN_DEL_SYSTEM_USER"')
        return 1

    query = urlencode(
        {
            "fields": "name,language,status,category,components",
            "limit": "100",
        }
    )
    url = f"https://graph.facebook.com/{graph_version}/{waba_id}/message_templates?{query}"

    templates: list[dict] = []
    try:
        while url:
            payload = _fetch(url, token)
            templates.extend(payload.get("data") or [])
            url = (payload.get("paging") or {}).get("next")
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

    if not templates:
        print(f"No hay plantillas visibles para la WABA {waba_id}.")
        return 0

    print(f"Plantillas encontradas para WABA {waba_id}: {len(templates)}")
    for template in sorted(templates, key=lambda item: (item.get("name") or "", item.get("language") or "")):
        components = template.get("components") or []
        print("-" * 80)
        print(f"Nombre: {template.get('name')}")
        print(f"Idioma: {template.get('language')}")
        print(f"Estado: {template.get('status')}")
        print(f"Categoria: {template.get('category')}")
        print(f"Variables BODY: {_body_variable_count(components)}")
        for component in components:
            component_type = component.get("type")
            text = component.get("text")
            if text:
                preview = str(text).replace("\n", " ")[:180]
                print(f"{component_type}: {preview}")
            else:
                print(f"{component_type}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
