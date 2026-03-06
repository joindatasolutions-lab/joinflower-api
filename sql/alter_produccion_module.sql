CREATE TABLE IF NOT EXISTS Florista (
  idFlorista BIGINT PRIMARY KEY AUTO_INCREMENT,
  empresaID BIGINT NOT NULL,
  sucursalID BIGINT NOT NULL,
  nombre VARCHAR(150) NOT NULL,
  capacidadDiaria BIGINT NOT NULL,
  activo TINYINT(1) NOT NULL DEFAULT 1,
  especialidades TEXT NULL,
  createdAt DATETIME NULL,
  updatedAt DATETIME NULL,
  INDEX idx_florista_empresa_sucursal_activo (empresaID, sucursalID, activo)
);

CREATE TABLE IF NOT EXISTS Produccion (
  idProduccion BIGINT PRIMARY KEY AUTO_INCREMENT,
  empresaID BIGINT NOT NULL,
  sucursalID BIGINT NOT NULL,
  pedidoID BIGINT NOT NULL,
  floristaID BIGINT NULL,
  fechaProgramadaProduccion DATE NOT NULL,
  fechaAsignacion DATETIME NULL,
  fechaInicio DATETIME NULL,
  fechaFinalizacion DATETIME NULL,
  estado VARCHAR(30) NOT NULL,
  prioridad VARCHAR(20) NOT NULL DEFAULT 'MEDIA',
  observacionesInternas TEXT NULL,
  ordenProduccion BIGINT NULL,
  createdAt DATETIME NULL,
  updatedAt DATETIME NULL,
  UNIQUE KEY uq_produccion_pedido (pedidoID),
  INDEX idx_produccion_fecha_estado (fechaProgramadaProduccion, estado),
  INDEX idx_produccion_florista_fecha (floristaID, fechaProgramadaProduccion),
  INDEX idx_produccion_empresa_sucursal_fecha (empresaID, sucursalID, fechaProgramadaProduccion),
  CONSTRAINT fk_produccion_pedido FOREIGN KEY (pedidoID) REFERENCES Pedido(idPedido),
  CONSTRAINT fk_produccion_florista FOREIGN KEY (floristaID) REFERENCES Florista(idFlorista)
);

ALTER TABLE Produccion
  ADD COLUMN IF NOT EXISTS pedidoID BIGINT NULL AFTER sucursalID,
  ADD COLUMN IF NOT EXISTS floristaID BIGINT NULL AFTER pedidoID,
  ADD COLUMN IF NOT EXISTS fechaProgramadaProduccion DATE NULL AFTER floristaID,
  ADD COLUMN IF NOT EXISTS fechaAsignacion DATETIME NULL AFTER fechaProgramadaProduccion,
  ADD COLUMN IF NOT EXISTS fechaFinalizacion DATETIME NULL AFTER fechaInicio,
  ADD COLUMN IF NOT EXISTS estado VARCHAR(30) NULL AFTER fechaFinalizacion,
  ADD COLUMN IF NOT EXISTS prioridad VARCHAR(20) NULL AFTER estado,
  ADD COLUMN IF NOT EXISTS observacionesInternas TEXT NULL AFTER prioridad,
  ADD COLUMN IF NOT EXISTS ordenProduccion BIGINT NULL AFTER observacionesInternas;

UPDATE Produccion p
LEFT JOIN PedidoDetalle pd ON pd.idPedidoDetalle = p.pedidoDetalleID
SET p.pedidoID = pd.pedidoID
WHERE p.pedidoID IS NULL;

UPDATE Produccion
SET floristaID = empleadoID
WHERE floristaID IS NULL AND empleadoID IS NOT NULL;

UPDATE Produccion
SET fechaFinalizacion = fechaFin
WHERE fechaFinalizacion IS NULL AND fechaFin IS NOT NULL;

UPDATE Produccion p
LEFT JOIN Entrega e ON e.pedidoID = p.pedidoID
SET p.fechaProgramadaProduccion = DATE(e.fechaEntrega)
WHERE p.fechaProgramadaProduccion IS NULL AND e.fechaEntrega IS NOT NULL;

UPDATE Produccion
SET fechaProgramadaProduccion = CURRENT_DATE()
WHERE fechaProgramadaProduccion IS NULL;

UPDATE Produccion
SET estado = 'Pendiente'
WHERE estado IS NULL OR TRIM(estado) = '';

UPDATE Produccion
SET prioridad = 'MEDIA'
WHERE prioridad IS NULL OR TRIM(prioridad) = '';

ALTER TABLE Produccion
  MODIFY COLUMN pedidoDetalleID BIGINT NULL,
  MODIFY COLUMN estadoProduccionID BIGINT NULL;
