ALTER TABLE petalops.pedido
  ADD COLUMN IF NOT EXISTS domicilio_obsequiado BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS omitir_costo_domicilio BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS domicilio_original NUMERIC(12,2),
  ADD COLUMN IF NOT EXISTS descuento_domicilio NUMERIC(12,2);

UPDATE petalops.pedido
SET domicilio_obsequiado = FALSE
WHERE domicilio_obsequiado IS NULL;

UPDATE petalops.pedido
SET omitir_costo_domicilio = FALSE
WHERE omitir_costo_domicilio IS NULL;
