-- Configuracion de modulos por empresa (override)
-- Permite habilitar/deshabilitar modulos por tenant sin afectar otras empresas.

CREATE TABLE IF NOT EXISTS EmpresaModulo (
  empresaID BIGINT NOT NULL,
  modulo VARCHAR(80) NOT NULL,
  activo TINYINT(1) NOT NULL DEFAULT 1,
  updatedAt DATETIME NOT NULL,
  PRIMARY KEY (empresaID, modulo),
  INDEX idx_empresa_modulo_activo (empresaID, activo),
  CONSTRAINT fk_empresamodulo_empresa FOREIGN KEY (empresaID) REFERENCES Empresa(idEmpresa)
);
