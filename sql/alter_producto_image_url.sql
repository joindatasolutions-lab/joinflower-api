-- Agregar campo image_url a tabla producto
ALTER TABLE petalops.producto
ADD COLUMN IF NOT EXISTS image_url TEXT NULL;

-- Crear índice para optimizar consultas
CREATE INDEX IF NOT EXISTS idx_producto_image_url ON petalops.producto(id_producto) WHERE image_url IS NOT NULL;
