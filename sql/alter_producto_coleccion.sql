ALTER TABLE petalops.producto
ADD COLUMN IF NOT EXISTS coleccion VARCHAR(100) NULL;

COMMENT ON COLUMN petalops.producto.coleccion IS
'Coleccion comercial del producto en catalogo, por ejemplo General, Madres o Amor y amistad.';
