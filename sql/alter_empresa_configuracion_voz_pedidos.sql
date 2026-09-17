ALTER TABLE petalops.empresa_configuracion_asignacion
ADD COLUMN IF NOT EXISTS voz_pedidos_activa BOOLEAN NOT NULL DEFAULT FALSE;
