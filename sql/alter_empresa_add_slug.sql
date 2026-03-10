ALTER TABLE Empresa
ADD COLUMN slug VARCHAR(50) NULL;

CREATE UNIQUE INDEX uk_empresa_slug ON Empresa(slug);

-- Ejemplos de asignacion inicial
-- UPDATE Empresa SET slug = 'petalops' WHERE idEmpresa = 1;
-- UPDATE Empresa SET slug = 'flora' WHERE idEmpresa = 3;
