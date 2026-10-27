-- Arqueo fisico y control de diferencias de caja.
-- Los campos son anulables para distinguir cierres historicos sin conteo fisico.

ALTER TABLE petalops.caja
  ADD COLUMN IF NOT EXISTS total_contado NUMERIC NULL,
  ADD COLUMN IF NOT EXISTS sobrante NUMERIC NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS faltante NUMERIC NOT NULL DEFAULT 0;

ALTER TABLE petalops.caja
  DROP CONSTRAINT IF EXISTS ck_caja_total_contado_no_negativo,
  DROP CONSTRAINT IF EXISTS ck_caja_sobrante_no_negativo,
  DROP CONSTRAINT IF EXISTS ck_caja_faltante_no_negativo;

ALTER TABLE petalops.caja
  ADD CONSTRAINT ck_caja_total_contado_no_negativo
    CHECK (total_contado IS NULL OR total_contado >= 0),
  ADD CONSTRAINT ck_caja_sobrante_no_negativo CHECK (sobrante >= 0),
  ADD CONSTRAINT ck_caja_faltante_no_negativo CHECK (faltante >= 0);

COMMENT ON COLUMN petalops.caja.total_contado IS
  'Dinero fisico contado durante el arqueo; NULL indica un registro historico sin conteo.';
COMMENT ON COLUMN petalops.caja.sobrante IS
  'Diferencia positiva entre total contado y efectivo esperado.';
COMMENT ON COLUMN petalops.caja.faltante IS
  'Diferencia positiva entre efectivo esperado y total contado.';
