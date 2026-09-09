import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import text
from sqlalchemy.orm import Session


PASSWORD_VAULT_KEY_ENV = "PASSWORD_VAULT_KEY"
PASSWORD_VAULT_KEY_VERSION_ENV = "PASSWORD_VAULT_KEY_VERSION"


class PasswordVaultError(RuntimeError):
    pass


def is_password_vault_enabled() -> bool:
    return bool(str(os.getenv(PASSWORD_VAULT_KEY_ENV, "")).strip())


def _fernet() -> Fernet:
    raw_key = str(os.getenv(PASSWORD_VAULT_KEY_ENV, "")).strip()
    if not raw_key:
        raise PasswordVaultError(f"{PASSWORD_VAULT_KEY_ENV} no configurada")

    try:
        return Fernet(raw_key.encode("utf-8"))
    except ValueError:
        derived_key = base64.urlsafe_b64encode(hashlib.sha256(raw_key.encode("utf-8")).digest())
        return Fernet(derived_key)


def encrypt_password(plain_password: str) -> str:
    if not plain_password:
        raise PasswordVaultError("La contrasena no puede estar vacia")
    return _fernet().encrypt(str(plain_password).encode("utf-8")).decode("utf-8")


def decrypt_password(encrypted_password: str) -> str:
    try:
        return _fernet().decrypt(str(encrypted_password).encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise PasswordVaultError("No fue posible desencriptar la contrasena almacenada") from exc


def ensure_password_vault_table(db: Session) -> None:
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS petalops.usuario_password_vault (
                usuario_id BIGINT PRIMARY KEY REFERENCES petalops.usuario(id_usuario) ON DELETE CASCADE,
                empresa_id BIGINT NOT NULL,
                encrypted_password TEXT NOT NULL,
                key_version VARCHAR(40) NOT NULL DEFAULT 'v1',
                updated_by BIGINT NULL,
                last_viewed_by BIGINT NULL,
                last_viewed_at TIMESTAMP NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_usuario_password_vault_empresa
            ON petalops.usuario_password_vault (empresa_id)
            """
        )
    )


def upsert_user_password_vault(
    db: Session,
    *,
    user_id: int,
    empresa_id: int,
    plain_password: str,
    actor_user_id: int | None = None,
) -> bool:
    if not is_password_vault_enabled():
        return False

    ensure_password_vault_table(db)
    encrypted_password = encrypt_password(plain_password)
    key_version = str(os.getenv(PASSWORD_VAULT_KEY_VERSION_ENV, "v1")).strip() or "v1"
    db.execute(
        text(
            """
            INSERT INTO petalops.usuario_password_vault (
                usuario_id, empresa_id, encrypted_password, key_version, updated_by, created_at, updated_at
            )
            VALUES (
                :usuario_id, :empresa_id, :encrypted_password, :key_version, :updated_by,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            ON CONFLICT (usuario_id) DO UPDATE
            SET empresa_id = EXCLUDED.empresa_id,
                encrypted_password = EXCLUDED.encrypted_password,
                key_version = EXCLUDED.key_version,
                updated_by = EXCLUDED.updated_by,
                updated_at = CURRENT_TIMESTAMP
            """
        ),
        {
            "usuario_id": int(user_id),
            "empresa_id": int(empresa_id),
            "encrypted_password": encrypted_password,
            "key_version": key_version,
            "updated_by": int(actor_user_id) if actor_user_id is not None else None,
        },
    )
    return True


def get_user_password_from_vault(db: Session, *, user_id: int) -> str | None:
    if not is_password_vault_enabled():
        return None

    ensure_password_vault_table(db)
    row = db.execute(
        text(
            """
            SELECT encrypted_password
            FROM petalops.usuario_password_vault
            WHERE usuario_id = :usuario_id
            LIMIT 1
            """
        ),
        {"usuario_id": int(user_id)},
    ).mappings().first()
    if not row:
        return None
    return decrypt_password(str(row["encrypted_password"]))


def mark_password_vault_viewed(db: Session, *, user_id: int, viewer_user_id: int) -> None:
    ensure_password_vault_table(db)
    db.execute(
        text(
            """
            UPDATE petalops.usuario_password_vault
            SET last_viewed_by = :viewer_user_id,
                last_viewed_at = CURRENT_TIMESTAMP
            WHERE usuario_id = :usuario_id
            """
        ),
        {
            "usuario_id": int(user_id),
            "viewer_user_id": int(viewer_user_id),
        },
    )
