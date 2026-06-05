-- Migración: campos marca y precio_venta para módulo Adicionales
-- Multitenant: empresa_id en todas las queries

ALTER TABLE petalops.insumo
  ADD COLUMN IF NOT EXISTS marca        varchar(100),
  ADD COLUMN IF NOT EXISTS precio_venta numeric(12,2);

COMMENT ON COLUMN petalops.insumo.marca        IS 'Marca del producto (uso principal: módulo Adicionales)';
COMMENT ON COLUMN petalops.insumo.precio_venta IS 'Precio de venta (uso principal: módulo Adicionales — permite calcular utilidad)';
