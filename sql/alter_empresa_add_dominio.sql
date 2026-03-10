ALTER TABLE Empresa
ADD COLUMN dominio VARCHAR(120) NULL;

CREATE INDEX idx_empresa_dominio ON Empresa(dominio);

-- Ejemplos de asignacion inicial
-- UPDATE Empresa SET dominio = 'petalops' WHERE idEmpresa = 1;
-- UPDATE Empresa SET dominio = 'flora' WHERE idEmpresa = 3;
