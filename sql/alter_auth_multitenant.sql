-- DROP TABLE statements removed for safe schema update. No data will be lost.
CREATE TABLE IF NOT EXISTS petalops."Empresa" (
  "idEmpresa" BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS petalops."Sucursal" (
  "idSucursal" BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  "empresaID" BIGINT
);

CREATE TABLE IF NOT EXISTS petalops."Pedido" (
  "idPedido" BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  "empresaID" BIGINT,
  "estadoPedidoID" BIGINT
);

CREATE TABLE IF NOT EXISTS petalops."Florista" (
  "idFlorista" BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  "empresaID" BIGINT,
  "sucursalID" BIGINT
);

CREATE TABLE IF NOT EXISTS petalops."Produccion" (
  "idProduccion" BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  "empresaID" BIGINT,
  "sucursalID" BIGINT,
  "pedidoID" BIGINT,
  "floristaID" BIGINT,
  "fechaProgramadaProduccion" DATE,
  "estado" VARCHAR(30)
);

-- Multi-tenant auth + RBAC + plan gating
-- Ejecutar en PostgreSQL sobre base compartida.



-- Ejecutar estos ALTER TABLE como sentencias individuales desde Python o psql
ALTER TABLE petalops."Empresa" ADD COLUMN IF NOT EXISTS nombreComercial VARCHAR(180);
ALTER TABLE petalops."Empresa" ADD COLUMN IF NOT EXISTS planID BIGINT;
ALTER TABLE petalops."Empresa" ADD COLUMN IF NOT EXISTS estado VARCHAR(20) NOT NULL DEFAULT 'Activo';


CREATE TABLE IF NOT EXISTS petalops."Rol" (
  "idRol" BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  "empresaID" BIGINT NOT NULL,
  "nombreRol" VARCHAR(80) NOT NULL,
  CONSTRAINT uq_rol_empresa_nombre UNIQUE ("empresaID", "nombreRol"),
  CONSTRAINT fk_rol_empresa FOREIGN KEY ("empresaID") REFERENCES "Empresa"("idEmpresa")
);

-- (Movido al final para asegurar que la tabla existe)

CREATE TABLE IF NOT EXISTS petalops."Usuario" (
  "idusuario" BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  "empresaID" BIGINT NOT NULL,
  "sucursalID" BIGINT NOT NULL,
  "nombre" VARCHAR(150) NOT NULL,
  "login" VARCHAR(80),
  "email" VARCHAR(180) NOT NULL,
  "passwordHash" VARCHAR(255) NOT NULL,
  "rolID" BIGINT NOT NULL,
  "estado" VARCHAR(20) NOT NULL DEFAULT 'Activo',
  "ultimoLogin" TIMESTAMP NULL,
  "createdAt" TIMESTAMP NULL,
  "updatedAt" TIMESTAMP NULL,
  CONSTRAINT uq_usuario_login UNIQUE ("login"),
  CONSTRAINT uq_usuario_empresa_email UNIQUE ("empresaID", "email"),
  CONSTRAINT fk_usuario_empresa FOREIGN KEY ("empresaID") REFERENCES "Empresa"("idEmpresa"),
  CONSTRAINT fk_usuario_rol FOREIGN KEY ("rolID") REFERENCES "Rol"("idRol")
);

CREATE TABLE IF NOT EXISTS petalops.PermisoModulo (
  rolID BIGINT NOT NULL,
  modulo VARCHAR(80) NOT NULL,
  puedeVer BOOLEAN NOT NULL DEFAULT FALSE,
  puedeCrear BOOLEAN NOT NULL DEFAULT FALSE,
  puedeEditar BOOLEAN NOT NULL DEFAULT FALSE,
  puedeEliminar BOOLEAN NOT NULL DEFAULT FALSE,
  PRIMARY KEY (rolID, modulo),
-- índice removido del bloque CREATE TABLE para PostgreSQL
  CONSTRAINT fk_permiso_rol FOREIGN KEY (rolID) REFERENCES "Rol"("idRol")
);

CREATE TABLE IF NOT EXISTS petalops.PlanModulo (
  planID BIGINT NOT NULL,
  modulo VARCHAR(80) NOT NULL,
  activo BOOLEAN NOT NULL DEFAULT TRUE,
  PRIMARY KEY (planID, modulo)
);


CREATE TABLE IF NOT EXISTS petalops."PermisoModulo" (
  "rolID" BIGINT NOT NULL,
  "modulo" VARCHAR(80) NOT NULL,
  "puedeVer" BOOLEAN NOT NULL DEFAULT FALSE,
  "puedeCrear" BOOLEAN NOT NULL DEFAULT FALSE,
  "puedeEditar" BOOLEAN NOT NULL DEFAULT FALSE,
  "puedeEliminar" BOOLEAN NOT NULL DEFAULT FALSE,
  PRIMARY KEY ("rolID", "modulo"),
  CONSTRAINT fk_permiso_rol FOREIGN KEY ("rolID") REFERENCES "Rol"("idRol")
);

-- Índices recomendados para aislamiento por empresa en tablas operativas ya existentes.
-- índices removidos para PostgreSQL

-- Índices adaptados a PostgreSQL (asegurar que todas las tablas existen antes de crear índices):

CREATE INDEX IF NOT EXISTS idx_rol_empresa ON petalops."Rol" ("empresaID");
CREATE INDEX IF NOT EXISTS idx_usuario_empresa_estado ON petalops."Usuario" ("empresaID", "estado");
CREATE INDEX IF NOT EXISTS idx_usuario_rol ON petalops."Usuario" ("rolID");
CREATE INDEX IF NOT EXISTS idx_permiso_modulo ON petalops."PermisoModulo" ("modulo");
CREATE INDEX IF NOT EXISTS idx_pedido_empresa_estado ON petalops."Pedido" ("empresaID", "estadoPedidoID");
CREATE INDEX IF NOT EXISTS idx_produccion_empresa_fecha_estado ON petalops."Produccion" ("empresaID", "fechaProgramadaProduccion", "estado");

