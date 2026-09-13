BEGIN;

ALTER TABLE petalops.empresa_configuracion_asignacion
  ADD COLUMN IF NOT EXISTS notificacion_pedido_aceptado_activa BOOLEAN NOT NULL DEFAULT TRUE,
  ADD COLUMN IF NOT EXISTS notificacion_pedido_entregado_activa BOOLEAN NOT NULL DEFAULT TRUE,
  ADD COLUMN IF NOT EXISTS notificacion_nuevo_pedido_domiciliario_activa BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE petalops.usuario
  ADD COLUMN IF NOT EXISTS celular VARCHAR(40);

ALTER TABLE petalops.whatsapp_notificacion
  ADD COLUMN IF NOT EXISTS usuario_destino_id BIGINT;

CREATE INDEX IF NOT EXISTS idx_whatsapp_notificacion_usuario_destino
  ON petalops.whatsapp_notificacion (usuario_destino_id);

COMMIT;
