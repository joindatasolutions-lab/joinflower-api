-- Login unico por usuario (sin pedir empresaID en pantalla de login)
-- Mantiene email como dato de contacto.

ALTER TABLE Usuario
  ADD COLUMN IF NOT EXISTS login VARCHAR(80) NULL;

-- Backfill seguro para usuarios existentes.
UPDATE Usuario
SET login = CONCAT('user', idUsuario)
WHERE login IS NULL OR TRIM(login) = '';

-- Normaliza a minusculas para consistencia en autenticacion.
UPDATE Usuario
SET login = LOWER(TRIM(login));

ALTER TABLE Usuario
  MODIFY COLUMN login VARCHAR(80) NOT NULL;

ALTER TABLE Usuario
  ADD UNIQUE INDEX uq_usuario_login (login);
