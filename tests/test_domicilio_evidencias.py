from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.core.security import get_current_auth_context
from app.database import get_db
from app.routers import domicilios
from app.schemas.auth import AuthContext


@pytest.fixture
def setup():
    app = FastAPI()
    app.include_router(domicilios.router)
    auth = AuthContext(
        userID=1, empresaID=3, sucursalID=3, rolID=1, rol="Admin",
        nombre="Admin", login="admin", email="admin@example.com",
        permisos={"domicilios": {"puedeVer": True}}, modulosActivosPlan={"domicilios"},
    )
    db = MagicMock()
    entrega = SimpleNamespace(
        idEntrega=6557, sucursalID=3, estadoEntregaID=4,
        firmaNombre="RECEPTOR", firmaDocumento="123", observaciones="PRUEBA",
        evidenciaFotoUrl="https://example.com/foto.png", firmaImagenUrl="https://example.com/firma.png",
    )
    db.query.return_value.filter.return_value.first.side_effect = [
        SimpleNamespace(idSucursal=3),
        SimpleNamespace(idPedido=6589, numeroPedido=100117, empresaID=3),
    ]
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = entrega
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_auth_context] = lambda: auth
    return TestClient(app), app, db, auth, entrega


URL = "/domicilios/pedidos/100117/evidencias?empresaID=3&sucursalID=3"


def test_evidencias(setup):
    client, _, db, _, _ = setup
    response = client.get(URL)
    assert response.status_code == 200
    assert response.json() == dict(
        numero_pedido=100117, id_pedido=6589, id_entrega=6557, estado="entregado",
        firma_nombre="RECEPTOR", firma_documento="123", observaciones="PRUEBA",
        evidencia_entrega_url="https://example.com/foto.png",
        evidencia_firma_url="https://example.com/firma.png",
    )
    filters = [str(arg) for call in db.query.return_value.filter.call_args_list for arg in call.args]
    assert any("pedido.numero_pedido" in item for item in filters)
    assert any("pedido.sucursal_id" in item for item in filters)
    assert any("entrega.empresa_id" in item for item in filters)
    assert any("entrega.pedido_id" in item for item in filters)


@pytest.mark.parametrize("photo,signature", [(None, None), ("", "https://example.com/firma.png")])
def test_missing_evidence(setup, photo, signature):
    client, _, _, _, entrega = setup
    entrega.evidenciaFotoUrl = photo
    entrega.firmaImagenUrl = signature
    response = client.get(URL)
    assert response.status_code == 200
    assert response.json()["evidencia_entrega_url"] is None
    assert response.json()["evidencia_firma_url"] == signature


def test_without_delivery(setup):
    client, _, db, _, _ = setup
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
    response = client.get(URL)
    assert response.status_code == 200
    assert response.json()["id_entrega"] is None
    assert response.json()["evidencia_firma_url"] is None


@pytest.mark.parametrize("rows,status", [([object(), None], 404), ([None], 403)])
def test_missing_order_or_invalid_branch(setup, rows, status):
    client, _, db, _, _ = setup
    db.query.return_value.filter.return_value.first.side_effect = rows
    assert client.get(URL).status_code == status


@pytest.mark.parametrize("change", ["empresa", "sucursal", "permiso"])
def test_forbidden(setup, change):
    client, _, db, auth, _ = setup
    if change == "empresa":
        auth.empresaID = 4
    elif change == "sucursal":
        auth.rol = "Domiciliario"
        auth.sucursalID = 4
    else:
        auth.permisos = {}
    assert client.get(URL).status_code == 403
    db.query.assert_not_called()


@pytest.mark.parametrize("role", ["Domiciliario", "Vendedor", "Operador"])
def test_any_role_with_module_access_can_read(setup, role):
    client, _, _, auth, _ = setup
    auth.rol = role
    assert client.get(URL).status_code == 200


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer invalid"}])
def test_unauthenticated(setup, headers):
    client, app, db, _, _ = setup
    del app.dependency_overrides[get_current_auth_context]
    assert client.get(URL, headers=headers).status_code == 401
    db.query.assert_not_called()


def test_query_failure_is_error(setup):
    client, _, db, _, _ = setup
    db.query.return_value.filter.return_value.first.side_effect = SQLAlchemyError("failure")
    assert client.get(URL).status_code == 500
