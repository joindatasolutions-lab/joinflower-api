import os

import pytest
from fastapi.testclient import TestClient

from app.main import app


pytestmark = pytest.mark.integration


USERS = {
    "flora.admin": {
        "password": "FloraAdmin2026*",
        "expected_role": "Admin",
        "allowed_modules": {"pedidos", "produccion", "domicilios", "inventario", "reportes", "usuarios"},
    },
    "flora.pedidos": {
        "password": "FloraPedidos2026*",
        "expected_role": "PEDIDOS",
        "allowed_modules": {"pedidos"},
    },
    "flora.florista1": {
        "password": "FloraFlorista12026*",
        "expected_role": "FLORISTA",
        "allowed_modules": {"produccion"},
    },
    "flora.domi1": {
        "password": "FloraDomi12026*",
        "expected_role": "DOMICILIARIO",
        "allowed_modules": {"domicilios"},
    },
    "flora.inventario": {
        "password": "FloraInventario2026*",
        "expected_role": "INVENTARIO",
        "allowed_modules": {"inventario"},
    },
}


def _integration_enabled() -> bool:
    return os.getenv("RUN_INTEGRATION_TESTS", "0") == "1"


@pytest.mark.parametrize("login", list(USERS.keys()))
def test_role_module_access_matrix(login: str):
    if not _integration_enabled():
        pytest.skip("Integration test skipped. Set RUN_INTEGRATION_TESTS=1 to execute.")

    cfg = USERS[login]
    client = TestClient(app)

    login_resp = client.post("/auth/login", json={"login": login, "password": cfg["password"]})
    assert login_resp.status_code == 200, f"login failed for {login}: {login_resp.text}"

    token = login_resp.json()["accessToken"]
    headers = {"Authorization": f"Bearer {token}"}

    me_resp = client.get("/auth/me", headers=headers)
    assert me_resp.status_code == 200, f"/auth/me failed for {login}: {me_resp.text}"

    me = me_resp.json()
    assert int(me["empresaID"]) == 3
    assert bool(me.get("esGlobalJoin")) is False
    assert str(me.get("rol", "")).strip().lower() == str(cfg["expected_role"]).strip().lower()

    active_modules = {str(m).strip().lower() for m in me.get("modulosActivosPlan", [])}
    assert cfg["allowed_modules"].issubset(active_modules), (
        f"{login} does not have expected modules. expected>={cfg['allowed_modules']} got={active_modules}"
    )

    empresa_id = int(me["empresaID"])

    # Representative endpoint checks per module
    checks = {
        "pedidos": client.get(
            "/pedidos",
            params={"empresaID": empresa_id, "page": 1, "pageSize": 5},
            headers=headers,
        ),
        "produccion": client.get(
            "/produccion",
            params={"empresaID": empresa_id},
            headers=headers,
        ),
        "domicilios": client.get(
            "/domicilios",
            params={"empresaID": empresa_id},
            headers=headers,
        ),
        "inventario": client.get(
            "/inventario",
            params={"empresaID": empresa_id},
            headers=headers,
        ),
    }

    for module, response in checks.items():
        if module in cfg["allowed_modules"]:
            assert response.status_code == 200, f"{login} should access {module}: {response.status_code} {response.text}"
        else:
            assert response.status_code in {403}, (
                f"{login} should be blocked from {module}, got {response.status_code} {response.text}"
            )

    users_resp = client.get("/auth/usuarios", params={"empresaID": empresa_id}, headers=headers)
    if login == "flora.admin":
        assert users_resp.status_code == 200, users_resp.text
    else:
        assert users_resp.status_code == 403, users_resp.text
