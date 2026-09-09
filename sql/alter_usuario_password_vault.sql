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
);

CREATE INDEX IF NOT EXISTS ix_usuario_password_vault_empresa
ON petalops.usuario_password_vault (empresa_id);
