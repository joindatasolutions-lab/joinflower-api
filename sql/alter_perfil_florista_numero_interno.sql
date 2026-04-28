ALTER TABLE petalops.perfil_florista
ADD COLUMN IF NOT EXISTS numero_interno bigint;

WITH ranked AS (
    SELECT
        pf.empleado_id,
        ROW_NUMBER() OVER (
            PARTITION BY e.empresa_id, e.sucursal_id
            ORDER BY e.id_empleado
        ) AS numero_generado
    FROM petalops.perfil_florista pf
    JOIN petalops.empleado e
      ON e.id_empleado = pf.empleado_id
    WHERE upper(COALESCE(e.cargo, '')) = 'FLORISTA'
)
UPDATE petalops.perfil_florista pf
SET numero_interno = ranked.numero_generado
FROM ranked
WHERE pf.empleado_id = ranked.empleado_id
  AND pf.numero_interno IS NULL;
