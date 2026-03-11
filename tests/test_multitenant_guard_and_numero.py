import os

import pytest
from fastapi.testclient import TestClient

from app.main import app


pytestmark = pytest.mark.integration


def test_tenant_guard_and_numero_pedido_presence():
    # This test uses the configured DB and seeded auth data.
    if os.getenv("RUN_INTEGRATION_TESTS", "0") != "1":
        pytest.skip("Integration test skipped. Set RUN_INTEGRATION_TESTS=1 to execute.")

    client = TestClient(app)

    login = client.post(
        "/auth/login",
        json={"login": "joinadmin", "password": "Admin123*"},
    )
    assert login.status_code == 200, login.text

    token = login.json()["accessToken"]
    headers = {"Authorization": f"Bearer {token}"}

    me = client.get("/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    auth_me = me.json()

    empresa_id = int(auth_me["empresaID"])

    ok_list = client.get(
        "/pedidos",
        params={
            "empresaID": empresa_id,
            "page": 1,
            "pageSize": 20,
        },
        headers=headers,
    )
    assert ok_list.status_code == 200, ok_list.text

    payload = ok_list.json()
    items = payload.get("items", [])
    assert isinstance(items, list)
    assert len(items) > 0, "No hay pedidos para validar"

    # Each item shown in frontend must expose numeroPedido.
    for item in items[:10]:
        assert "numeroPedido" in item
        assert item["numeroPedido"] is not None

    first = items[0]
    detalle = client.get(f"/pedido/{first['pedidoID']}/detalle", headers=headers)
    assert detalle.status_code == 200, detalle.text
    detalle_body = detalle.json()
    assert "numeroPedido" in detalle_body
    assert detalle_body["numeroPedido"] is not None

    # Cross-tenant query with same token must be forbidden.
    wrong_empresa_id = empresa_id + 99999
    forbidden = client.get(
        "/pedidos",
        params={
            "empresaID": wrong_empresa_id,
            "page": 1,
            "pageSize": 20,
        },
        headers=headers,
    )
    assert forbidden.status_code == 403, forbidden.text
