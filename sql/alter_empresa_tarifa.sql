ALTER TABLE petalops.empresa
ADD COLUMN IF NOT EXISTS tarifa BIGINT NOT NULL DEFAULT 2500;

UPDATE petalops.empresa
SET tarifa = CASE
    WHEN id_empresa = 3 THEN 1500
    ELSE 2500
END;
