-- Indices enfocados en asignacion por fecha y tenancy para bajo costo en Cloud Run.
-- Ejecutar una sola vez en entorno productivo.

ALTER TABLE Produccion
  ADD INDEX idx_produccion_empresa_fecha (empresaID, fechaProgramadaProduccion);
