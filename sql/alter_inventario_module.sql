-- Modulo Inventario (multi-tenant)

CREATE TABLE IF NOT EXISTS "Proveedor" (
  "idProveedor" BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  "empresaID" BIGINT NOT NULL,
  "nombreProveedor" VARCHAR(150) NOT NULL,
  "codigoProveedor" VARCHAR(80),
  "activo" BOOLEAN NOT NULL DEFAULT TRUE,
  "createdAt" TIMESTAMP,
  "updatedAt" TIMESTAMP,
  CONSTRAINT uq_proveedor_empresa_codigo UNIQUE ("empresaID", "codigoProveedor"),
  CONSTRAINT fk_proveedor_empresa FOREIGN KEY ("empresaID") REFERENCES "Empresa"("idEmpresa")
);

CREATE INDEX IF NOT EXISTS idx_proveedor_empresa_activo ON "Proveedor" ("empresaID", "activo");

CREATE TABLE IF NOT EXISTS "Inventario" (
  "idInventario" BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  "empresaID" BIGINT NOT NULL,
  "codigo" VARCHAR(80) NOT NULL,
  "nombre" VARCHAR(180) NOT NULL,
  "categoria" VARCHAR(80) NOT NULL,
  "subcategoria" VARCHAR(80),
  "color" VARCHAR(80),
  "descripcion" VARCHAR(255),
  "proveedorID" BIGINT,
  "codigoProveedor" VARCHAR(80),
  "stockActual" DECIMAL(12,2) NOT NULL DEFAULT 0,
  "stockMinimo" DECIMAL(12,2) NOT NULL DEFAULT 0,
  "valorUnitario" DECIMAL(12,2) NOT NULL DEFAULT 0,
  "activo" BOOLEAN NOT NULL DEFAULT TRUE,
  "fechaUltimaActualizacion" TIMESTAMP,
  "createdAt" TIMESTAMP,
  "updatedAt" TIMESTAMP,
  CONSTRAINT uq_inventario_empresa_codigo UNIQUE ("empresaID", "codigo"),
  CONSTRAINT fk_inventario_empresa FOREIGN KEY ("empresaID") REFERENCES "Empresa"("idEmpresa"),
  CONSTRAINT fk_inventario_proveedor FOREIGN KEY ("proveedorID") REFERENCES "Proveedor"("idProveedor")
);

CREATE INDEX IF NOT EXISTS idx_inventario_empresa_categoria ON "Inventario" ("empresaID", "categoria");
CREATE INDEX IF NOT EXISTS idx_inventario_empresa_activo ON "Inventario" ("empresaID", "activo");
CREATE INDEX IF NOT EXISTS idx_inventario_empresa_stock ON "Inventario" ("empresaID", "stockActual", "stockMinimo");

CREATE TABLE IF NOT EXISTS "MovimientoInventario" (
  "idMovimiento" BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  "empresaID" BIGINT NOT NULL,
  "inventarioID" BIGINT NOT NULL,
  "tipoMovimiento" VARCHAR(20) NOT NULL,
  "cantidad" DECIMAL(12,2) NOT NULL,
  "fecha" TIMESTAMP NOT NULL,
  "motivo" VARCHAR(250),
  "usuarioID" BIGINT,
  "createdAt" TIMESTAMP,
  CONSTRAINT fk_movinv_empresa FOREIGN KEY ("empresaID") REFERENCES "Empresa"("idEmpresa"),
  CONSTRAINT fk_movinv_inventario FOREIGN KEY ("inventarioID") REFERENCES "Inventario"("idInventario"),
  CONSTRAINT fk_movinv_usuario FOREIGN KEY ("usuarioID") REFERENCES "Usuario"("idusuario")
);

CREATE INDEX IF NOT EXISTS idx_movinv_empresa_fecha ON "MovimientoInventario" ("empresaID", "fecha");
CREATE INDEX IF NOT EXISTS idx_movinv_inventario_fecha ON "MovimientoInventario" ("inventarioID", "fecha");
