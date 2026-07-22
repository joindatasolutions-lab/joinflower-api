ALTER TABLE petalops.empleado
    ADD COLUMN IF NOT EXISTS vehiculo VARCHAR(80);

ALTER TABLE petalops.empleado
    ADD COLUMN IF NOT EXISTS telefono VARCHAR(40);

ALTER TABLE petalops.empleado
    ADD COLUMN IF NOT EXISTS tipo VARCHAR(80);

ALTER TABLE petalops.empleado
    ADD COLUMN IF NOT EXISTS estado VARCHAR(20);

ALTER TABLE petalops.empleado
    ADD COLUMN IF NOT EXISTS placa VARCHAR(20);

ALTER TABLE petalops.empleado
    ADD COLUMN IF NOT EXISTS detalle_vehiculo VARCHAR(160);
