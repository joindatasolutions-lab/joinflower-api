-- Modulo Domicilios (operacion ultima milla)
-- Nota: La tabla Entrega ya existe para datos de checkout.
-- Este script la extiende para trazabilidad operativa.

CREATE TABLE IF NOT EXISTS Domiciliario (
  idDomiciliario BIGINT PRIMARY KEY AUTO_INCREMENT,
  empresaID BIGINT NOT NULL,
  sucursalID BIGINT NOT NULL,
  nombre VARCHAR(180) NOT NULL,
  telefono VARCHAR(40) NULL,
  activo TINYINT(1) NOT NULL DEFAULT 1,
  createdAt DATETIME NULL,
  updatedAt DATETIME NULL,
  INDEX idx_domiciliario_empresa_sucursal_activo (empresaID, sucursalID, activo),
  CONSTRAINT fk_domiciliario_empresa FOREIGN KEY (empresaID) REFERENCES Empresa(idEmpresa)
);

ALTER TABLE Entrega
  ADD COLUMN IF NOT EXISTS sucursalID BIGINT NULL,
  ADD COLUMN IF NOT EXISTS produccionID BIGINT NULL,
  ADD COLUMN IF NOT EXISTS domiciliarioID BIGINT NULL,
  ADD COLUMN IF NOT EXISTS fechaAsignacion DATETIME NULL,
  ADD COLUMN IF NOT EXISTS fechaEntregaProgramada DATETIME NULL,
  ADD COLUMN IF NOT EXISTS estado VARCHAR(30) NULL,
  ADD COLUMN IF NOT EXISTS latitudEntrega DECIMAL(10,7) NULL,
  ADD COLUMN IF NOT EXISTS longitudEntrega DECIMAL(10,7) NULL,
  ADD COLUMN IF NOT EXISTS firmaNombre VARCHAR(180) NULL,
  ADD COLUMN IF NOT EXISTS firmaDocumento VARCHAR(50) NULL,
  ADD COLUMN IF NOT EXISTS firmaImagenUrl TEXT NULL,
  ADD COLUMN IF NOT EXISTS evidenciaFotoUrl TEXT NULL,
  ADD COLUMN IF NOT EXISTS observaciones TEXT NULL,
  ADD COLUMN IF NOT EXISTS motivoNoEntregado TEXT NULL,
  ADD COLUMN IF NOT EXISTS intentoNumero INT NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS reprogramadaPara DATETIME NULL;

ALTER TABLE Entrega
  ADD INDEX idx_entrega_fecha_estado (fechaEntrega, estado),
  ADD INDEX idx_entrega_domiciliario_estado (domiciliarioID, estado),
  ADD INDEX idx_entrega_empresa_fecha (empresaID, fechaEntrega),
  ADD INDEX idx_entrega_empresa_fecha_programada (empresaID, fechaEntregaProgramada),
  ADD INDEX idx_entrega_produccion (produccionID);

ALTER TABLE Entrega
  ADD CONSTRAINT fk_entrega_domiciliario FOREIGN KEY (domiciliarioID) REFERENCES Domiciliario(idDomiciliario),
  ADD CONSTRAINT fk_entrega_produccion FOREIGN KEY (produccionID) REFERENCES Produccion(idProduccion);
