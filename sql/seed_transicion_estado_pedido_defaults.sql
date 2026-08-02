-- Reglas base para flujo de estados de pedidos por empresa.
-- Esta tabla define transiciones permitidas; el historial real vive en pedido_auditoria.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_trans_pedido_estado_origen'
    ) THEN
        ALTER TABLE petalops.transicion_estado_pedido
        ADD CONSTRAINT fk_trans_pedido_estado_origen
        FOREIGN KEY (estado_origen_id)
        REFERENCES petalops.estado_pedido(id_estado_pedido);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_trans_pedido_estado_destino'
    ) THEN
        ALTER TABLE petalops.transicion_estado_pedido
        ADD CONSTRAINT fk_trans_pedido_estado_destino
        FOREIGN KEY (estado_destino_id)
        REFERENCES petalops.estado_pedido(id_estado_pedido);
    END IF;
END $$;

WITH empresas AS (
    SELECT id_empresa
    FROM petalops.empresa
    WHERE COALESCE(estado, 1) = 1
), estados AS (
    SELECT id_estado_pedido, UPPER(TRIM(nombre_estado)) AS nombre_estado
    FROM petalops.estado_pedido
), pares(origen, destino) AS (
    VALUES
        ('CREADO', 'APROBADO'),
        ('CREADO', 'CANCELADO'),
        ('PENDIENTE', 'APROBADO'),
        ('PENDIENTE', 'CANCELADO'),
        ('APROBADO', 'CANCELADO')
)
INSERT INTO petalops.transicion_estado_pedido (
    empresa_id,
    estado_origen_id,
    estado_destino_id,
    created_at
)
SELECT
    e.id_empresa,
    eo.id_estado_pedido,
    ed.id_estado_pedido,
    CURRENT_TIMESTAMP
FROM empresas e
JOIN pares p ON TRUE
JOIN estados eo ON eo.nombre_estado = p.origen
JOIN estados ed ON ed.nombre_estado = p.destino
ON CONFLICT (empresa_id, estado_origen_id, estado_destino_id) DO NOTHING;
