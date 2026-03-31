DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='florista' AND column_name='trabajossimultaneospermitidos') THEN
    ALTER TABLE "Florista" ADD COLUMN trabajosSimultaneosPermitidos INT NOT NULL DEFAULT 1;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='florista' AND column_name='estado') THEN
    ALTER TABLE "Florista" ADD COLUMN estado VARCHAR(20) NOT NULL DEFAULT 'Activo' CHECK (estado IN ('Activo','Inactivo','Incapacidad'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='florista' AND column_name='fechainicioincapacidad') THEN
    ALTER TABLE "Florista" ADD COLUMN fechaInicioIncapacidad DATE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='florista' AND column_name='fechafinincapacidad') THEN
    ALTER TABLE "Florista" ADD COLUMN fechaFinIncapacidad DATE;
  END IF;
END$$;

UPDATE "Florista"
SET estado = CASE
  WHEN estado IS NULL OR estado = '' THEN (CASE WHEN COALESCE(activo, TRUE) = TRUE THEN 'Activo' ELSE 'Inactivo' END)
  ELSE estado
END;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='produccion' AND column_name='tiempoestimadomin') THEN
    ALTER TABLE "Produccion" ADD COLUMN tiempoEstimadoMin INT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='produccion' AND column_name='tiemporealmin') THEN
    ALTER TABLE "Produccion" ADD COLUMN tiempoRealMin INT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='produccion' AND column_name='ordenproduccion') THEN
    ALTER TABLE "Produccion" ADD COLUMN ordenProduccion INT;
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='producto' AND column_name='tiempobaseproduccionmin') THEN
    ALTER TABLE "Producto" ADD COLUMN tiempoBaseProduccionMin INT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='producto' AND column_name='nivelcomplejidad') THEN
    ALTER TABLE "Producto" ADD COLUMN nivelComplejidad VARCHAR(30);
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='pedido' AND column_name='version') THEN
    ALTER TABLE "Pedido" ADD COLUMN version INT NOT NULL DEFAULT 1;
  END IF;
END$$;

CREATE TABLE IF NOT EXISTS "ProduccionHistorial" (
  "idProduccionHistorial" BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  "empresaID" BIGINT NOT NULL,
  "sucursalID" BIGINT NOT NULL,
  "produccionID" BIGINT NOT NULL,
  "floristaAnteriorID" BIGINT,
  "floristaNuevoID" BIGINT,
  "fechaCambio" TIMESTAMP NOT NULL,
  "motivo" TEXT NOT NULL,
  "usuarioCambio" VARCHAR(120) NOT NULL,
  CONSTRAINT fk_historial_produccion FOREIGN KEY ("produccionID") REFERENCES "Produccion"("idProduccion")
);

CREATE INDEX IF NOT EXISTS idx_historial_produccion_fecha ON "ProduccionHistorial" ("produccionID", "fechaCambio");
CREATE INDEX IF NOT EXISTS idx_historial_empresa_sucursal_fecha ON "ProduccionHistorial" ("empresaID", "sucursalID", "fechaCambio");

