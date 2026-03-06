ALTER TABLE Florista
  ADD COLUMN IF NOT EXISTS trabajosSimultaneosPermitidos INT NOT NULL DEFAULT 1 AFTER capacidadDiaria,
  ADD COLUMN IF NOT EXISTS estado ENUM('Activo','Inactivo','Incapacidad') NOT NULL DEFAULT 'Activo' AFTER trabajosSimultaneosPermitidos,
  ADD COLUMN IF NOT EXISTS fechaInicioIncapacidad DATE NULL AFTER estado,
  ADD COLUMN IF NOT EXISTS fechaFinIncapacidad DATE NULL AFTER fechaInicioIncapacidad;

UPDATE Florista
SET estado = CASE
  WHEN estado IS NULL OR estado = '' THEN (CASE WHEN COALESCE(activo, 1) = 1 THEN 'Activo' ELSE 'Inactivo' END)
  ELSE estado
END;

ALTER TABLE Produccion
  ADD COLUMN IF NOT EXISTS tiempoEstimadoMin INT NULL AFTER fechaFinalizacion,
  ADD COLUMN IF NOT EXISTS tiempoRealMin INT NULL AFTER tiempoEstimadoMin,
  ADD COLUMN IF NOT EXISTS ordenProduccion INT NULL AFTER observacionesInternas;

ALTER TABLE Producto
  ADD COLUMN IF NOT EXISTS tiempoBaseProduccionMin INT NULL AFTER ivaIncluido,
  ADD COLUMN IF NOT EXISTS nivelComplejidad VARCHAR(30) NULL AFTER tiempoBaseProduccionMin;

ALTER TABLE Pedido
  ADD COLUMN IF NOT EXISTS version INT NOT NULL DEFAULT 1 AFTER estadoPedidoID;

CREATE TABLE IF NOT EXISTS ProduccionHistorial (
  idProduccionHistorial BIGINT PRIMARY KEY AUTO_INCREMENT,
  empresaID BIGINT NOT NULL,
  sucursalID BIGINT NOT NULL,
  produccionID BIGINT NOT NULL,
  floristaAnteriorID BIGINT NULL,
  floristaNuevoID BIGINT NULL,
  fechaCambio DATETIME NOT NULL,
  motivo TEXT NOT NULL,
  usuarioCambio VARCHAR(120) NOT NULL,
  INDEX idx_historial_produccion_fecha (produccionID, fechaCambio),
  INDEX idx_historial_empresa_sucursal_fecha (empresaID, sucursalID, fechaCambio),
  CONSTRAINT fk_historial_produccion FOREIGN KEY (produccionID) REFERENCES Produccion(idProduccion)
);

