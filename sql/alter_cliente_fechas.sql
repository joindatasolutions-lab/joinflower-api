ALTER TABLE petalops.cliente
ADD COLUMN IF NOT EXISTS fecha_cumpleanos DATE NULL;

ALTER TABLE petalops.cliente
ADD COLUMN IF NOT EXISTS fecha_aniversario DATE NULL;
