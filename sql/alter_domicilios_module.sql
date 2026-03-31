-- Modulo Domicilios (operacion ultima milla)
-- Nota: La tabla Entrega ya existe para datos de checkout.
-- Este script la extiende para trazabilidad operativa.

CREATE TABLE IF NOT EXISTS "Domiciliario" (
  "idDomiciliario" BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  "empresaID" BIGINT NOT NULL,
  "sucursalID" BIGINT NOT NULL,
  "nombre" VARCHAR(180) NOT NULL,
  "telefono" VARCHAR(40),
  "activo" BOOLEAN NOT NULL DEFAULT TRUE,
  "createdAt" TIMESTAMP,
  "updatedAt" TIMESTAMP,
  CONSTRAINT fk_domiciliario_empresa FOREIGN KEY ("empresaID") REFERENCES "Empresa"("idEmpresa")
);

CREATE INDEX IF NOT EXISTS idx_domiciliario_empresa_sucursal_activo ON "Domiciliario" ("empresaID", "sucursalID", "activo");


