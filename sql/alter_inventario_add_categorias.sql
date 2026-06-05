-- Migración: inventario - categorías florales y arreglos/recetas
-- Multitenant: todos los cambios usan empresa_id

-- 1. Agregar nuevas columnas a petalops.insumo
ALTER TABLE petalops.insumo
  ADD COLUMN IF NOT EXISTS categoria   varchar(80),
  ADD COLUMN IF NOT EXISTS subcategoria varchar(80),
  ADD COLUMN IF NOT EXISTS color        varchar(80),
  ADD COLUMN IF NOT EXISTS descripcion  text,
  ADD COLUMN IF NOT EXISTS tamano       varchar(50),
  ADD COLUMN IF NOT EXISTS fecha_vencimiento date;

-- 2. Migrar datos existentes: unidad_medida tenía el valor de categoría
--    (el backend mapeaba payload.categoria → unidad_medida por error de diseño)
UPDATE petalops.insumo
SET categoria = unidad_medida
WHERE categoria IS NULL AND unidad_medida IS NOT NULL;

-- 3. Índice para filtrar por empresa + categoría
CREATE INDEX IF NOT EXISTS idx_insumo_empresa_categoria
  ON petalops.insumo (empresa_id, categoria);

-- 4. Agregar tipo de movimiento "Pérdida" si no existe
INSERT INTO petalops.tipo_movimiento (codigo, nombre, afecta_stock, signo)
SELECT 'PERDIDA', 'Pérdida', true, -1
WHERE NOT EXISTS (
  SELECT 1 FROM petalops.tipo_movimiento
  WHERE lower(codigo) IN ('perdida', 'pérdida')
);

-- 5. Tabla receta (cabecera de arreglo floral con ingredientes)
CREATE TABLE IF NOT EXISTS petalops.receta (
  id_receta   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  empresa_id  bigint NOT NULL,
  nombre      varchar(200) NOT NULL,
  descripcion text,
  activo      boolean NOT NULL DEFAULT true,
  created_at  timestamp NOT NULL DEFAULT now(),
  updated_at  timestamp,
  CONSTRAINT uq_receta_empresa_nombre UNIQUE (empresa_id, nombre),
  CONSTRAINT fk_receta_empresa FOREIGN KEY (empresa_id) REFERENCES petalops.empresa(id_empresa)
);

CREATE INDEX IF NOT EXISTS idx_receta_empresa ON petalops.receta (empresa_id, activo);

-- 6. Tabla receta_detalle (ingredientes por receta)
CREATE TABLE IF NOT EXISTS petalops.receta_detalle (
  id_receta_detalle bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  empresa_id        bigint NOT NULL,
  receta_id         bigint NOT NULL,
  inventario_id     bigint NOT NULL,
  cantidad          numeric(12,4) NOT NULL DEFAULT 1,
  created_at        timestamp NOT NULL DEFAULT now(),
  CONSTRAINT uq_receta_detalle_receta_inv UNIQUE (receta_id, inventario_id),
  CONSTRAINT fk_receta_detalle_receta     FOREIGN KEY (receta_id)     REFERENCES petalops.receta(id_receta) ON DELETE CASCADE,
  CONSTRAINT fk_receta_detalle_inventario FOREIGN KEY (inventario_id) REFERENCES petalops.inventario(id_inventario),
  CONSTRAINT fk_receta_detalle_empresa    FOREIGN KEY (empresa_id)    REFERENCES petalops.empresa(id_empresa)
);

CREATE INDEX IF NOT EXISTS idx_receta_detalle_receta  ON petalops.receta_detalle (receta_id);
CREATE INDEX IF NOT EXISTS idx_receta_detalle_empresa ON petalops.receta_detalle (empresa_id);
