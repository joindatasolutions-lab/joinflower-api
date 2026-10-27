-- Precios por paquete para inventario.
-- Migracion aditiva: no modifica valores ni comportamiento de registros existentes.

ALTER TABLE petalops.inventario
  ADD COLUMN IF NOT EXISTS costo_paquete NUMERIC(12, 2) NULL;

ALTER TABLE petalops.insumo
  ADD COLUMN IF NOT EXISTS precio_venta_paquete NUMERIC(12, 2) NULL;

COMMENT ON COLUMN petalops.inventario.costo_paquete IS
  'Costo de compra por paquete; aplica a todas las categorias de inventario.';

COMMENT ON COLUMN petalops.insumo.precio_venta_paquete IS
  'Precio de venta al publico por paquete; se utiliza para la categoria Flores.';
