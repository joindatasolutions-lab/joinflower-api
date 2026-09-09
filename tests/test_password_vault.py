from cryptography.fernet import Fernet

from app.services.password_vault import (
    PASSWORD_VAULT_KEY_ENV,
    decrypt_password,
    encrypt_password,
    is_password_vault_enabled,
    upsert_user_password_vault,
)


class _FakeDb:
    def __init__(self):
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return _FakeResult()


class _FakeResult:
    def mappings(self):
        return self

    def first(self):
        return None


def test_password_vault_encrypts_and_decrypts_with_configured_key(monkeypatch):
    monkeypatch.setenv(PASSWORD_VAULT_KEY_ENV, Fernet.generate_key().decode("utf-8"))

    encrypted = encrypt_password("NuevaClave2026*")

    assert encrypted != "NuevaClave2026*"
    assert decrypt_password(encrypted) == "NuevaClave2026*"


def test_password_vault_is_disabled_without_key(monkeypatch):
    monkeypatch.delenv(PASSWORD_VAULT_KEY_ENV, raising=False)

    assert is_password_vault_enabled() is False
    assert upsert_user_password_vault(
        _FakeDb(),
        user_id=10,
        empresa_id=3,
        plain_password="NuevaClave2026*",
        actor_user_id=1,
    ) is False


def test_password_vault_upsert_never_stores_plain_password(monkeypatch):
    monkeypatch.setenv(PASSWORD_VAULT_KEY_ENV, Fernet.generate_key().decode("utf-8"))
    db = _FakeDb()

    assert upsert_user_password_vault(
        db,
        user_id=10,
        empresa_id=3,
        plain_password="NuevaClave2026*",
        actor_user_id=1,
    ) is True

    params = db.calls[-1][1]
    assert params["encrypted_password"] != "NuevaClave2026*"
    assert decrypt_password(params["encrypted_password"]) == "NuevaClave2026*"
