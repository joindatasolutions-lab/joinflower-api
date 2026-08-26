import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from app.main import app
from app.routers import webhooks


client = TestClient(app)


def test_verificacion_webhook_exitosa(monkeypatch):
    monkeypatch.setattr(webhooks, "WHATSAPP_VERIFY_TOKEN", "mi-token-secreto")

    response = client.get(
        "/webhooks/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "mi-token-secreto",
            "hub.challenge": "1234567890",
        },
    )

    assert response.status_code == 200
    assert response.text == "1234567890"


def test_verificacion_webhook_token_invalido(monkeypatch):
    monkeypatch.setattr(webhooks, "WHATSAPP_VERIFY_TOKEN", "mi-token-secreto")

    response = client.get(
        "/webhooks/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "token-incorrecto",
            "hub.challenge": "1234567890",
        },
    )

    assert response.status_code == 403


def test_verificacion_webhook_sin_token_configurado(monkeypatch):
    monkeypatch.setattr(webhooks, "WHATSAPP_VERIFY_TOKEN", "")

    response = client.get(
        "/webhooks/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "cualquier-cosa",
            "hub.challenge": "1234567890",
        },
    )

    assert response.status_code == 403


def test_evento_webhook_firma_valida(monkeypatch):
    monkeypatch.setattr(webhooks, "WHATSAPP_APP_SECRET", "app-secret-de-prueba")

    payload = {"object": "whatsapp_business_account", "entry": []}
    raw_body = json.dumps(payload).encode("utf-8")
    firma = hmac.new(b"app-secret-de-prueba", raw_body, hashlib.sha256).hexdigest()

    response = client.post(
        "/webhooks/whatsapp",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": f"sha256={firma}",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_evento_webhook_firma_invalida_se_rechaza(monkeypatch):
    monkeypatch.setattr(webhooks, "WHATSAPP_APP_SECRET", "app-secret-de-prueba")

    payload = {"object": "whatsapp_business_account", "entry": []}
    raw_body = json.dumps(payload).encode("utf-8")

    response = client.post(
        "/webhooks/whatsapp",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": "sha256=firma-incorrecta",
        },
    )

    assert response.status_code == 401


def test_evento_webhook_sin_firma_se_rechaza(monkeypatch):
    monkeypatch.setattr(webhooks, "WHATSAPP_APP_SECRET", "app-secret-de-prueba")

    payload = {"object": "whatsapp_business_account", "entry": []}

    response = client.post("/webhooks/whatsapp", json=payload)

    assert response.status_code == 401


def test_evento_webhook_sin_secreto_configurado_se_acepta(monkeypatch):
    monkeypatch.setattr(webhooks, "WHATSAPP_APP_SECRET", "")

    payload = {"object": "whatsapp_business_account", "entry": []}

    response = client.post("/webhooks/whatsapp", json=payload)

    assert response.status_code == 200
