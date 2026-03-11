import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func

from app.database import SessionLocal
from app.main import app
from app.models.estadopedido import EstadoPedido
from app.models.pedido import Pedido


pytestmark = pytest.mark.integration


def test_get_entrega_mensaje_for_approved_order():
    if os.getenv("RUN_INTEGRATION_TESTS", "0") != "1":
        pytest.skip("Integration test skipped. Set RUN_INTEGRATION_TESTS=1 to execute.")

    client = TestClient(app)

    login = client.post("/auth/login", json={"login": "joinadmin", "password": "Admin123*"})
    assert login.status_code == 200, login.text

    token = login.json()["accessToken"]
    headers = {"Authorization": f"Bearer {token}"}

    pedido_id = None
    session = SessionLocal()
    try:
        row = (
            session.query(Pedido.idPedido)
            .join(EstadoPedido, EstadoPedido.idEstadoPedido == Pedido.estadoPedidoID)
            .filter(func.upper(EstadoPedido.nombreEstado) == "APROBADO")
            .order_by(Pedido.idPedido.desc())
            .first()
        )
        if row:
            pedido_id = int(row[0])
    finally:
        session.close()

    if not pedido_id:
        pytest.skip("No hay pedidos APROBADO para validar /entregas/pedido/{id}/mensaje")

    resp = client.get(f"/entregas/pedido/{pedido_id}/mensaje", headers=headers)
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert int(body["pedidoId"]) == int(pedido_id)
    assert "mensaje" in body
    assert "destinatario" in body
    assert "fechaEntrega" in body
    assert "firma" in body


def test_get_entrega_mensaje_returns_400_for_non_approved_order():
    if os.getenv("RUN_INTEGRATION_TESTS", "0") != "1":
        pytest.skip("Integration test skipped. Set RUN_INTEGRATION_TESTS=1 to execute.")

    client = TestClient(app)

    login = client.post("/auth/login", json={"login": "joinadmin", "password": "Admin123*"})
    assert login.status_code == 200, login.text

    token = login.json()["accessToken"]
    headers = {"Authorization": f"Bearer {token}"}

    pedido_id = None
    session = SessionLocal()
    try:
        row = (
            session.query(Pedido.idPedido)
            .join(EstadoPedido, EstadoPedido.idEstadoPedido == Pedido.estadoPedidoID)
            .filter(func.upper(EstadoPedido.nombreEstado) != "APROBADO")
            .order_by(Pedido.idPedido.desc())
            .first()
        )
        if row:
            pedido_id = int(row[0])
    finally:
        session.close()

    if not pedido_id:
        pytest.skip("No hay pedidos en estado distinto a APROBADO para validar respuesta 400")

    resp = client.get(f"/entregas/pedido/{pedido_id}/mensaje", headers=headers)
    assert resp.status_code == 400, resp.text

    body = resp.json()
    assert "detail" in body
    assert "APROBADO" in str(body["detail"]).upper()
