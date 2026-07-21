ALTER TABLE petalops.producto
ADD COLUMN IF NOT EXISTS codigo_catalogo VARCHAR(50);

COMMENT ON COLUMN petalops.producto.codigo_catalogo IS 'Codigo visible de catalogo usado como codigo de arreglo para empresa_id=3';
