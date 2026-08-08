from fastapi.testclient import TestClient

import app.routers.auth as auth_router
from app.core.security import get_current_auth_context
from app.main import app
from app.schemas.auth import AuthContext


def _auth_context(*, rol: str = "Admin", permisos: dict | None = None, empresa_id: int = 3) -> AuthContext:
    return AuthContext(
        userID=10,
        empresaID=empresa_id,
        empresaNombre="Flora",
        empresaSlug="flora",
        sucursalID=3,
        rolID=20,
        planID=1,
        rol=rol,
        nombre="Usuario Test",
        login="usuario.test",
        email="usuario.test@example.com",
        esGlobalJoin=False,
        ultimoLogin=None,
        permisos=permisos or {},
        modulosActivosPlan=set((permisos or {}).keys()),
    )


def test_admin_productos_session_sets_cookie_without_returning_token():
    app.dependency_overrides[get_current_auth_context] = lambda: _auth_context()
    client = TestClient(app)

    try:
        response = client.post("/auth/admin-productos/session")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"url": "https://adminpetalops.joindata.com.co/"}
    assert "accessToken" not in response.text

    set_cookie = response.headers["set-cookie"]
    assert "admin_productos_session=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert "SameSite=lax" in set_cookie


def test_admin_productos_session_allows_product_permissions():
    app.dependency_overrides[get_current_auth_context] = lambda: _auth_context(
        rol="Inventarista",
        permisos={"catalogo": {"puedeVer": True, "puedeCrear": False, "puedeEditar": True, "puedeEliminar": False}},
    )
    client = TestClient(app)

    try:
        response = client.post("/auth/admin-productos/session")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200


def test_admin_productos_session_rejects_non_product_user():
    app.dependency_overrides[get_current_auth_context] = lambda: _auth_context(
        rol="Pedidos",
        permisos={"pedidos": {"puedeVer": True, "puedeCrear": True, "puedeEditar": False, "puedeEliminar": False}},
    )
    client = TestClient(app)

    try:
        response = client.post("/auth/admin-productos/session")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


def test_admin_productos_session_delete_clears_cookie():
    client = TestClient(app)

    response = client.delete("/auth/admin-productos/session")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    set_cookie = response.headers["set-cookie"]
    assert "admin_productos_session=" in set_cookie
    assert "Max-Age=0" in set_cookie


def test_admin_productos_exchange_requires_cookie():
    client = TestClient(app)

    response = client.post("/auth/admin-productos/exchange")

    assert response.status_code == 401


def test_admin_productos_exchange_returns_admin_token_and_clears_cookie(monkeypatch):
    auth_context = _auth_context()
    app.dependency_overrides[get_current_auth_context] = lambda: auth_context
    monkeypatch.setattr(auth_router, "get_current_auth_context", lambda token, db: auth_context)
    client = TestClient(app)

    try:
        session_response = client.post("/auth/admin-productos/session")
        bridge_token = session_response.cookies.get("admin_productos_session")
        client.cookies.set("admin_productos_session", bridge_token)
        exchange_response = client.post("/auth/admin-productos/exchange")
        client.cookies.set("admin_productos_session", bridge_token)
        replay_response = client.post("/auth/admin-productos/exchange")
    finally:
        app.dependency_overrides.clear()

    assert session_response.status_code == 200
    assert exchange_response.status_code == 200
    payload = exchange_response.json()
    assert payload["accessToken"]
    assert payload["tokenType"] == "bearer"
    assert payload["user"]["userID"] == 10
    assert payload["user"]["empresaID"] == 3

    set_cookie = exchange_response.headers["set-cookie"]
    assert "admin_productos_session=" in set_cookie
    assert "Max-Age=0" in set_cookie
    assert replay_response.status_code == 401
