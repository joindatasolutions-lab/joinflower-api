-- Reglas base para flujo de estados de produccion por empresa.
-- Esta tabla define transiciones permitidas; el historial real vive en produccion_historial.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_trans_produccion_estado_origen'
    ) THEN
        ALTER TABLE petalops.transicion_estado_produccion
        ADD CONSTRAINT fk_trans_produccion_estado_origen
        FOREIGN KEY (estado_origen_id)
        REFERENCES petalops.estado_produccion(id_estado_produccion);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_trans_produccion_estado_destino'
    ) THEN
        ALTER TABLE petalops.transicion_estado_produccion
        ADD CONSTRAINT fk_trans_produccion_estado_destino
        FOREIGN KEY (estado_destino_id)
        REFERENCES petalops.estado_produccion(id_estado_produccion);
    END IF;
END $$;

WITH empresas AS (
    SELECT id_empresa
    FROM petalops.empresa
    WHERE COALESCE(estado, 1) = 1
), estados AS (
    SELECT id_estado_produccion, LOWER(TRIM(COALESCE(codigo, nombre))) AS codigo
    FROM petalops.estado_produccion
), pares(origen, destino) AS (
    VALUES
        ('pendiente', 'en_proceso'),
        ('pendiente', 'cancelado'),
        ('en_proceso', 'terminado'),
        ('en_proceso', 'cancelado')
)
INSERT INTO petalops.transicion_estado_produccion (
    empresa_id,
    estado_origen_id,
    estado_destino_id,
    created_at
)
SELECT
    e.id_empresa,
    eo.id_estado_produccion,
    ed.id_estado_produccion,
    CURRENT_TIMESTAMP
FROM empresas e
JOIN pares p ON TRUE
JOIN estados eo ON eo.codigo = p.origen
JOIN estados ed ON ed.codigo = p.destino
WHERE NOT EXISTS (
    SELECT 1
    FROM petalops.transicion_estado_produccion tep
    WHERE tep.empresa_id = e.id_empresa
      AND tep.estado_origen_id = eo.id_estado_produccion
      AND tep.estado_destino_id = ed.id_estado_produccion
);