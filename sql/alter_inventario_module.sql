-- Modulo Inventario (multi-tenant)

CREATE TABLE IF NOT EXISTS Proveedor (
  idProveedor BIGINT PRIMARY KEY AUTO_INCREMENT,
  empresaID BIGINT NOT NULL,
  nombreProveedor VARCHAR(150) NOT NULL,
  codigoProveedor VARCHAR(80) NULL,
  activo TINYINT(1) NOT NULL DEFAULT 1,
  createdAt DATETIME NULL,
  updatedAt DATETIME NULL,
  UNIQUE KEY uq_proveedor_empresa_codigo (empresaID, codigoProveedor),
  INDEX idx_proveedor_empresa_activo (empresaID, activo),
  CONSTRAINT fk_proveedor_empresa FOREIGN KEY (empresaID) REFERENCES Empresa(idEmpresa)
);

CREATE TABLE IF NOT EXISTS Inventario (
  idInventario BIGINT PRIMARY KEY AUTO_INCREMENT,
  empresaID BIGINT NOT NULL,
  codigo VARCHAR(80) NOT NULL,
  nombre VARCHAR(180) NOT NULL,
  categoria VARCHAR(80) NOT NULL,
  subcategoria VARCHAR(80) NULL,
  color VARCHAR(80) NULL,
  descripcion VARCHAR(255) NULL,
  proveedorID BIGINT NULL,
  codigoProveedor VARCHAR(80) NULL,
  stockActual DECIMAL(12,2) NOT NULL DEFAULT 0,
  stockMinimo DECIMAL(12,2) NOT NULL DEFAULT 0,
  valorUnitario DECIMAL(12,2) NOT NULL DEFAULT 0,
  activo TINYINT(1) NOT NULL DEFAULT 1,
  fechaUltimaActualizacion DATETIME NULL,
  createdAt DATETIME NULL,
  updatedAt DATETIME NULL,
  UNIQUE KEY uq_inventario_empresa_codigo (empresaID, codigo),
  INDEX idx_inventario_empresa_categoria (empresaID, categoria),
  INDEX idx_inventario_empresa_activo (empresaID, activo),
  INDEX idx_inventario_empresa_stock (empresaID, stockActual, stockMinimo),
  CONSTRAINT fk_inventario_empresa FOREIGN KEY (empresaID) REFERENCES Empresa(idEmpresa),
  CONSTRAINT fk_inventario_proveedor FOREIGN KEY (proveedorID) REFERENCES Proveedor(idProveedor)
);

CREATE TABLE IF NOT EXISTS MovimientoInventario (
  idMovimiento BIGINT PRIMARY KEY AUTO_INCREMENT,
  empresaID BIGINT NOT NULL,
  inventarioID BIGINT NOT NULL,
  tipoMovimiento VARCHAR(20) NOT NULL,
  cantidad DECIMAL(12,2) NOT NULL,
  fecha DATETIME NOT NULL,
  motivo VARCHAR(250) NULL,
  usuarioID BIGINT NULL,
  createdAt DATETIME NULL,
  INDEX idx_movinv_empresa_fecha (empresaID, fecha),
  INDEX idx_movinv_inventario_fecha (inventarioID, fecha),
  CONSTRAINT fk_movinv_empresa FOREIGN KEY (empresaID) REFERENCES Empresa(idEmpresa),
  CONSTRAINT fk_movinv_inventario FOREIGN KEY (inventarioID) REFERENCES Inventario(idInventario),
  CONSTRAINT fk_movinv_usuario FOREIGN KEY (usuarioID) REFERENCES Usuario(idUsuario)
);
