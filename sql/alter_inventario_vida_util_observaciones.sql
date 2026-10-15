ALTER TABLE petalops.insumo
  ADD COLUMN IF NOT EXISTS dias_vida_util INTEGER NULL,
  ADD COLUMN IF NOT EXISTS observaciones TEXT NULL;

COMMENT ON COLUMN petalops.insumo.dias_vida_util IS
'Vida util estimada del producto en dias.';

COMMENT ON COLUMN petalops.insumo.observaciones IS
'Notas opcionales propias del producto de inventario.';

ALTER TABLE petalops.insumo
  DROP CONSTRAINT IF EXISTS ck_insumo_dias_vida_util_no_negativo;

ALTER TABLE petalops.insumo
  ADD CONSTRAINT ck_insumo_dias_vida_util_no_negativo
  CHECK (dias_vida_util IS NULL OR dias_vida_util >= 0);
