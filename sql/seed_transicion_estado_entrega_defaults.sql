-- Seed idempotente de transiciones operativas por empresa para el modulo de domicilios.
-- Evita que tenants sin catalogo inicial queden bloqueados en Pendiente -> Asignado.

INSERT INTO petalops.transicion_estado_entrega (
    empresa_id,
    estado_origen_id,
    estado_destino_id,
    created_at
)
SELECT
    e.id_empresa,
    t.estado_origen_id,
    t.estado_destino_id,
    CURRENT_TIMESTAMP
FROM petalops.empresa e
CROSS JOIN (
    VALUES
        (1, 2), -- Pendiente -> Asignado
        (1, 6), -- Pendiente -> Cancelado
        (2, 3), -- Asignado -> En ruta
        (2, 6), -- Asignado -> Cancelado
        (3, 4), -- En ruta -> Entregado
        (3, 5), -- En ruta -> No entregado
        (5, 2), -- No entregado -> Asignado
        (5, 6)  -- No entregado -> Cancelado
) AS t(estado_origen_id, estado_destino_id)
LEFT JOIN petalops.transicion_estado_entrega existing
    ON existing.empresa_id = e.id_empresa
   AND existing.estado_origen_id = t.estado_origen_id
   AND existing.estado_destino_id = t.estado_destino_id
WHERE existing.id_tran_estado_ent IS NULL;
