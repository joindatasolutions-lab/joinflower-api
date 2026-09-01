-- Auditoria y trazabilidad del modulo de inventario.
-- Script idempotente: no modifica datos existentes ni elimina objetos.

ALTER TABLE petalops.movimiento_inventario
  ADD COLUMN IF NOT EXISTS estado VARCHAR(20) NOT NULL DEFAULT 'Registrado',
  ADD COLUMN IF NOT EXISTS anulado_at TIMESTAMP NULL,
  ADD COLUMN IF NOT EXISTS anulado_por_usuario_id BIGINT NULL,
  ADD COLUMN IF NOT EXISTS motivo_anulacion TEXT NULL,
  ADD COLUMN IF NOT EXISTS stock_anterior NUMERIC(12, 2) NULL,
  ADD COLUMN IF NOT EXISTS stock_nuevo NUMERIC(12, 2) NULL,
  ADD COLUMN IF NOT EXISTS referencia VARCHAR(80) NULL,
  ADD COLUMN IF NOT EXISTS proveedor_id BIGINT NULL,
  ADD COLUMN IF NOT EXISTS numero_factura VARCHAR(80) NULL,
  ADD COLUMN IF NOT EXISTS responsable VARCHAR(150) NULL,
  ADD COLUMN IF NOT EXISTS unidad VARCHAR(50) NULL,
  ADD COLUMN IF NOT EXISTS precio_unitario NUMERIC(12, 2) NULL,
  ADD COLUMN IF NOT EXISTS fecha_vencimiento DATE NULL,
  ADD COLUMN IF NOT EXISTS evidencia_url TEXT NULL,
  ADD COLUMN IF NOT EXISTS pedido_referencia VARCHAR(80) NULL,
  ADD COLUMN IF NOT EXISTS observaciones TEXT NULL,
  ADD COLUMN IF NOT EXISTS movimiento_origen_id BIGINT NULL;

UPDATE petalops.movimiento_inventario
SET referencia = CONCAT('MOV-', id_movimiento)
WHERE referencia IS NULL;

CREATE INDEX IF NOT EXISTS idx_movimiento_inventario_empresa_estado
  ON petalops.movimiento_inventario (empresa_id, estado);

CREATE INDEX IF NOT EXISTS idx_movimiento_inventario_inventario_estado
  ON petalops.movimiento_inventario (inventario_id, estado);

CREATE INDEX IF NOT EXISTS idx_movimiento_inventario_origen
  ON petalops.movimiento_inventario (movimiento_origen_id);
