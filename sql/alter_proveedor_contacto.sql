-- Datos de contacto para proveedores de inventario (telefono, email, direccion).
-- Columnas nullable y aditivas: no afectan filas existentes.

ALTER TABLE petalops.proveedor
ADD COLUMN IF NOT EXISTS telefono VARCHAR(30) NULL;

ALTER TABLE petalops.proveedor
ADD COLUMN IF NOT EXISTS email VARCHAR(150) NULL;

ALTER TABLE petalops.proveedor
ADD COLUMN IF NOT EXISTS direccion VARCHAR(255) NULL;
