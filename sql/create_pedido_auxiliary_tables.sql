-- Ejecutar antes de desplegar los endpoints de pedidos.
BEGIN;
CREATE TABLE IF NOT EXISTS petalops.pedido_auditoria (
              id_audit BIGSERIAL PRIMARY KEY,
              empresa_id BIGINT NOT NULL,
              sucursal_id BIGINT NOT NULL,
              pedido_id BIGINT NOT NULL,
              actor_user_id BIGINT,
              actor_login VARCHAR(120) NOT NULL,
              accion VARCHAR(60) NOT NULL,
              estado_origen_id BIGINT,
              estado_destino_id BIGINT,
              detalle_json TEXT,
              created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
CREATE TABLE IF NOT EXISTS petalops.pedido_alerta_voz (
              id_alerta BIGSERIAL PRIMARY KEY,
              empresa_id BIGINT NOT NULL,
              sucursal_id BIGINT,
              pedido_id BIGINT NOT NULL,
              created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
              CONSTRAINT uq_pedido_alerta_voz_empresa_pedido UNIQUE (empresa_id, pedido_id)
            );
CREATE INDEX IF NOT EXISTS idx_pedido_auditoria_empresa_fecha ON petalops.pedido_auditoria (empresa_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pedido_auditoria_pedido ON petalops.pedido_auditoria (empresa_id, pedido_id);
CREATE INDEX IF NOT EXISTS idx_pedido_alerta_voz_empresa_fecha ON petalops.pedido_alerta_voz (empresa_id, created_at DESC);
COMMIT;
