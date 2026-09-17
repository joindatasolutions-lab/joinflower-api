CREATE TABLE IF NOT EXISTS petalops.pedido_alerta_voz (
  id_alerta BIGSERIAL PRIMARY KEY,
  empresa_id BIGINT NOT NULL,
  sucursal_id BIGINT,
  pedido_id BIGINT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_pedido_alerta_voz_empresa_pedido UNIQUE (empresa_id, pedido_id)
);

CREATE INDEX IF NOT EXISTS idx_pedido_alerta_voz_empresa_fecha
ON petalops.pedido_alerta_voz (empresa_id, created_at DESC);
