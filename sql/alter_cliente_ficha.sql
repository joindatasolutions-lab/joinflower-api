BEGIN;

CREATE TABLE IF NOT EXISTS petalops.cliente_perfil (
    cliente_id BIGINT PRIMARY KEY REFERENCES petalops.cliente(cliente_id),
    empresa_id BIGINT NOT NULL REFERENCES petalops.empresa(id_empresa),
    direccion VARCHAR(500),
    canal_preferido VARCHAR(100),
    ocasion_preferida VARCHAR(100),
    preferencias TEXT,
    updated_at TIMESTAMP NOT NULL DEFAULT timezone('America/Bogota', now())
);

CREATE TABLE IF NOT EXISTS petalops.cliente_interaccion (
    id BIGSERIAL PRIMARY KEY,
    empresa_id BIGINT NOT NULL REFERENCES petalops.empresa(id_empresa),
    cliente_id BIGINT NOT NULL REFERENCES petalops.cliente(cliente_id),
    tipo VARCHAR(20) NOT NULL CHECK (tipo IN ('NOTE', 'COMMUNICATION')),
    contenido TEXT NOT NULL CHECK (length(trim(contenido)) > 0),
    canal VARCHAR(20),
    direccion VARCHAR(20),
    ocurrido_at TIMESTAMP NOT NULL,
    autor_id BIGINT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT timezone('America/Bogota', now()),
    CHECK ((tipo = 'NOTE' AND canal IS NULL AND direccion IS NULL) OR
           (tipo = 'COMMUNICATION' AND canal IS NOT NULL AND direccion IS NOT NULL
            AND canal IN ('WHATSAPP', 'EMAIL', 'PHONE', 'IN_PERSON', 'OTHER')
            AND direccion IN ('INBOUND', 'OUTBOUND')))
);
CREATE INDEX IF NOT EXISTS ix_cliente_interaccion_historial
    ON petalops.cliente_interaccion (empresa_id, cliente_id, tipo, ocurrido_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS ix_pedido_cliente_historial
    ON petalops.pedido (empresa_id, cliente_id, fecha_pedido DESC, id_pedido DESC);

COMMIT;
