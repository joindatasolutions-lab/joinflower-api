ALTER TABLE petalops.empresa
ADD COLUMN IF NOT EXISTS datos_transferencia_catalogo_activo BOOLEAN NOT NULL DEFAULT FALSE;

UPDATE petalops.empresa
SET datos_transferencia_catalogo_activo = FALSE
WHERE datos_transferencia_catalogo_activo IS NULL;
