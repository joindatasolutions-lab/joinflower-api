BEGIN;
CREATE TABLE IF NOT EXISTS petalops.pedido_operacion (
    empresa_id BIGINT NOT NULL,
    operacion VARCHAR(80) NOT NULL,
    clave VARCHAR(128) NOT NULL,
    payload_hash VARCHAR(64) NOT NULL,
    respuesta_json TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (empresa_id, operacion, clave)
);
COMMIT;
