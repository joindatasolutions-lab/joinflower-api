-- Venta rapida por unidad desde inventario.
-- Aditiva y segura: no cambia el comportamiento de los insumos existentes.

ALTER TABLE petalops.insumo
  ADD COLUMN IF NOT EXISTS vendible_unidad BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE petalops.insumo
  ADD COLUMN IF NOT EXISTS producto_venta_id BIGINT NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'fk_insumo_producto_venta'
      AND conrelid = 'petalops.insumo'::regclass
  ) THEN
    ALTER TABLE petalops.insumo
      ADD CONSTRAINT fk_insumo_producto_venta
      FOREIGN KEY (producto_venta_id)
      REFERENCES petalops.producto(id_producto);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_insumo_empresa_vendible_unidad
  ON petalops.insumo (empresa_id, vendible_unidad)
  WHERE vendible_unidad = TRUE;
