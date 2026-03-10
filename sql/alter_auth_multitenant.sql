-- Multi-tenant auth + RBAC + plan gating
-- Ejecutar en MySQL sobre base compartida.

ALTER TABLE Empresa
  ADD COLUMN IF NOT EXISTS nombreComercial VARCHAR(180) NULL,
  ADD COLUMN IF NOT EXISTS planID BIGINT NULL,
  ADD COLUMN IF NOT EXISTS estado VARCHAR(20) NOT NULL DEFAULT 'Activo';

CREATE TABLE IF NOT EXISTS Rol (
  idRol BIGINT PRIMARY KEY AUTO_INCREMENT,
  empresaID BIGINT NOT NULL,
  nombreRol VARCHAR(80) NOT NULL,
  UNIQUE KEY uq_rol_empresa_nombre (empresaID, nombreRol),
  INDEX idx_rol_empresa (empresaID),
  CONSTRAINT fk_rol_empresa FOREIGN KEY (empresaID) REFERENCES Empresa(idEmpresa)
);

CREATE TABLE IF NOT EXISTS Usuario (
  idUsuario BIGINT PRIMARY KEY AUTO_INCREMENT,
  empresaID BIGINT NOT NULL,
  sucursalID BIGINT NOT NULL,
  nombre VARCHAR(150) NOT NULL,
  login VARCHAR(80) NULL,
  email VARCHAR(180) NOT NULL,
  passwordHash VARCHAR(255) NOT NULL,
  rolID BIGINT NOT NULL,
  estado VARCHAR(20) NOT NULL DEFAULT 'Activo',
  ultimoLogin DATETIME NULL,
  createdAt DATETIME NULL,
  updatedAt DATETIME NULL,
  UNIQUE KEY uq_usuario_login (login),
  UNIQUE KEY uq_usuario_empresa_email (empresaID, email),
  INDEX idx_usuario_empresa_estado (empresaID, estado),
  INDEX idx_usuario_rol (rolID),
  CONSTRAINT fk_usuario_empresa FOREIGN KEY (empresaID) REFERENCES Empresa(idEmpresa),
  CONSTRAINT fk_usuario_rol FOREIGN KEY (rolID) REFERENCES Rol(idRol)
);

CREATE TABLE IF NOT EXISTS PermisoModulo (
  rolID BIGINT NOT NULL,
  modulo VARCHAR(80) NOT NULL,
  puedeVer TINYINT(1) NOT NULL DEFAULT 0,
  puedeCrear TINYINT(1) NOT NULL DEFAULT 0,
  puedeEditar TINYINT(1) NOT NULL DEFAULT 0,
  puedeEliminar TINYINT(1) NOT NULL DEFAULT 0,
  PRIMARY KEY (rolID, modulo),
  INDEX idx_permiso_modulo (modulo),
  CONSTRAINT fk_permiso_rol FOREIGN KEY (rolID) REFERENCES Rol(idRol)
);

CREATE TABLE IF NOT EXISTS PlanModulo (
  planID BIGINT NOT NULL,
  modulo VARCHAR(80) NOT NULL,
  activo TINYINT(1) NOT NULL DEFAULT 1,
  PRIMARY KEY (planID, modulo)
);

-- Índices recomendados para aislamiento por empresa en tablas operativas ya existentes.
ALTER TABLE Pedido
  ADD INDEX idx_pedido_empresa_estado (empresaID, estadoPedidoID);

ALTER TABLE Produccion
  ADD INDEX idx_produccion_empresa_fecha_estado (empresaID, fechaProgramadaProduccion, estado);
