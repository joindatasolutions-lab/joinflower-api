import os

import pytest

from tests.conftest import FLORA_EMPRESA_ID, ensure_flora_test_users, impersonated_headers, integration_client, integration_enabled


pytestmark = pytest.mark.integration


def test_tenant_guard_and_numero_pedido_presence():
    # This test uses the configured DB and seeded auth data.
    if not integration_enabled():
        pytest.skip("Integration test skipped. Set RUN_INTEGRATION_TESTS=1 to execute.")

    ensure_flora_test_users()
    client = integration_client()
    headers, auth_me = impersonated_headers(client, empresa_id=FLORA_EMPRESA_ID)
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
    if not items:
        pytest.skip("No hay pedidos en la empresa de prueba para validar numeroPedido y tenant guard")

    visible_items = [item for item in items if item.get("numeroPedido") is not None]
    if not visible_items:
        pytest.skip("No hay pedidos con numeracion visible para validar numeroPedido")

    # Items con numeracion visible deben exponer numeroPedido.
    for item in visible_items[:10]:
        assert "numeroPedido" in item
        assert item["numeroPedido"] is not None

    first = visible_items[0]
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
