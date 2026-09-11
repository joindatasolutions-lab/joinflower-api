BEGIN;

ALTER TABLE petalops.metodo_pago_catalogo
    ADD COLUMN IF NOT EXISTS cuenta VARCHAR(120),
    ADD COLUMN IF NOT EXISTS numero_cuenta VARCHAR(80),
    ADD COLUMN IF NOT EXISTS activas_cuentas_catalogo BOOLEAN NOT NULL DEFAULT FALSE;

UPDATE petalops.metodo_pago_catalogo
SET activas_cuentas_catalogo = FALSE
WHERE activas_cuentas_catalogo IS NULL;

COMMIT;
