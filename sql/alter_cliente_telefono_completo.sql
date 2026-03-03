ALTER TABLE Cliente
  ADD COLUMN IF NOT EXISTS telefonoCompleto VARCHAR(40) NULL AFTER indicativo;

UPDATE Cliente
SET telefonoCompleto = CONCAT(
  CASE
    WHEN indicativo IS NULL OR TRIM(indicativo) = '' THEN ''
    WHEN LEFT(TRIM(indicativo), 1) = '+' THEN TRIM(indicativo)
    ELSE CONCAT('+', TRIM(indicativo))
  END,
  COALESCE(TRIM(telefono), '')
)
WHERE (telefono IS NOT NULL AND TRIM(telefono) <> '');
