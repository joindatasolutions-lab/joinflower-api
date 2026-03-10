-- Usuario ligado a sucursal para contexto operativo

ALTER TABLE Usuario
  ADD COLUMN IF NOT EXISTS sucursalID BIGINT NULL;

UPDATE Usuario
SET sucursalID = COALESCE(sucursalID, 1)
WHERE sucursalID IS NULL;

ALTER TABLE Usuario
  MODIFY COLUMN sucursalID BIGINT NOT NULL;

ALTER TABLE Usuario
  ADD INDEX idx_usuario_empresa_sucursal_estado (empresaID, sucursalID, estado);
