-- Branding multiempresa
-- Ejecutar segun necesidad en ambientes donde falten columnas.

ALTER TABLE Empresa
ADD COLUMN logoUrl VARCHAR(500) NULL;

-- Si nombreComercial no existe en algun ambiente legado, ejecutar:
-- ALTER TABLE Empresa ADD COLUMN nombreComercial VARCHAR(150) NULL;
