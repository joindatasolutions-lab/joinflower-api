-- Remove legacy employee password mirror.
-- Authentication uses petalops.usuario.passwordhash exclusively.
ALTER TABLE petalops.empleado
  DROP COLUMN IF EXISTS password_hash;
