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
