from fastapi.testclient import TestClient

from app.main import app


def test_domiapp_login_preflight_is_allowed():
    client = TestClient(app)

    response = client.options(
        "/auth/login",
        headers={
            "Origin": "https://domiapp.joindata.com.co",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://domiapp.joindata.com.co"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_adminpetalops_session_preflight_is_allowed():
    client = TestClient(app)

    response = client.options(
        "/auth/admin-productos/session",
        headers={
            "Origin": "https://adminpetalops.joindata.com.co",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://adminpetalops.joindata.com.co"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_local_vite_preflight_is_allowed_for_empresa_create():
    client = TestClient(app)

    response = client.options(
        "/auth/usuarios/empresas",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_error_responses_keep_cors_for_local_vite_origin():
    client = TestClient(app)

    response = client.post(
        "/auth/usuarios/empresas",
        headers={"Origin": "http://127.0.0.1:5173"},
        json={"nombreComercial": "Tenant sin token"},
    )

    assert response.status_code in {401, 403}
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    assert response.headers["access-control-allow-credentials"] == "true"
