CREATE TABLE IF NOT EXISTS petalops.caja (
    id_caja BIGSERIAL PRIMARY KEY,
    empresa_id BIGINT NOT NULL,
    sucursal_id BIGINT NOT NULL,
    fecha DATE NOT NULL,
    base NUMERIC NOT NULL DEFAULT 0,
    efectivo NUMERIC NOT NULL DEFAULT 0,
    gasto NUMERIC NOT NULL DEFAULT 0,
    total_efectivo NUMERIC NOT NULL DEFAULT 0,
    guardado NUMERIC NOT NULL DEFAULT 0,
    nueva_base NUMERIC NOT NULL DEFAULT 0,
    observacion TEXT,
    usuario_id BIGINT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP,
    CONSTRAINT caja_empresa_fk FOREIGN KEY (empresa_id)
        REFERENCES petalops.empresa(id_empresa),
    CONSTRAINT caja_sucursal_fk FOREIGN KEY (sucursal_id)
        REFERENCES petalops.sucursal(id_sucursal),
    CONSTRAINT caja_usuario_fk FOREIGN KEY (usuario_id)
        REFERENCES petalops.usuario(id_usuario),
    CONSTRAINT caja_empresa_sucursal_fecha_uk UNIQUE (empresa_id, sucursal_id, fecha)
);

CREATE INDEX IF NOT EXISTS idx_caja_empresa_sucursal_fecha
    ON petalops.caja (empresa_id, sucursal_id, fecha DESC);

DO $$
BEGIN
    IF to_regclass('petalops.caja_apertura_cierre') IS NOT NULL THEN
        IF to_regclass('petalops.caja_gasto') IS NOT NULL THEN
            INSERT INTO petalops.caja (
                empresa_id, sucursal_id, fecha, base, efectivo, gasto,
                total_efectivo, guardado, nueva_base, observacion,
                usuario_id, created_at, updated_at
            )
            SELECT
                cac.empresa_id,
                cac.sucursal_id,
                cac.fecha_operacion AS fecha,
                cac.base_inicial AS base,
                0 AS efectivo,
                COALESCE(g.total_gastos, 0) AS gasto,
                cac.base_inicial - COALESCE(g.total_gastos, 0) AS total_efectivo,
                cac.monto_guardado AS guardado,
                cac.nueva_base,
                cac.observacion,
                cac.cerrado_por_usuario_id AS usuario_id,
                cac.created_at,
                cac.updated_at
            FROM petalops.caja_apertura_cierre cac
            LEFT JOIN (
                SELECT empresa_id,
                       sucursal_id,
                       fecha_operacion,
                       SUM(monto) AS total_gastos
                FROM petalops.caja_gasto
                GROUP BY empresa_id, sucursal_id, fecha_operacion
            ) g
              ON g.empresa_id = cac.empresa_id
             AND g.sucursal_id = cac.sucursal_id
             AND g.fecha_operacion = cac.fecha_operacion
            ON CONFLICT (empresa_id, sucursal_id, fecha)
            DO UPDATE SET
                base = EXCLUDED.base,
                gasto = EXCLUDED.gasto,
                total_efectivo = EXCLUDED.total_efectivo,
                guardado = EXCLUDED.guardado,
                nueva_base = EXCLUDED.nueva_base,
                observacion = EXCLUDED.observacion,
                usuario_id = EXCLUDED.usuario_id,
                updated_at = CURRENT_TIMESTAMP;
        ELSE
            INSERT INTO petalops.caja (
                empresa_id, sucursal_id, fecha, base, efectivo, gasto,
                total_efectivo, guardado, nueva_base, observacion,
                usuario_id, created_at, updated_at
            )
            SELECT
                empresa_id,
                sucursal_id,
                fecha_operacion AS fecha,
                base_inicial AS base,
                0 AS efectivo,
                0 AS gasto,
                base_inicial AS total_efectivo,
                monto_guardado AS guardado,
                nueva_base,
                observacion,
                cerrado_por_usuario_id AS usuario_id,
                created_at,
                updated_at
            FROM petalops.caja_apertura_cierre
            ON CONFLICT (empresa_id, sucursal_id, fecha)
            DO UPDATE SET
                base = EXCLUDED.base,
                total_efectivo = EXCLUDED.total_efectivo,
                guardado = EXCLUDED.guardado,
                nueva_base = EXCLUDED.nueva_base,
                observacion = EXCLUDED.observacion,
                usuario_id = EXCLUDED.usuario_id,
                updated_at = CURRENT_TIMESTAMP;
        END IF;
    END IF;
END $$;

DO $$
DECLARE
    legacy_filter TEXT := '';
    has_pago_metodo_monto BOOLEAN := FALSE;
BEGIN
    CREATE TEMP TABLE IF NOT EXISTS tmp_caja_efectivo_backfill (
        empresa_id BIGINT NOT NULL,
        sucursal_id BIGINT NOT NULL,
        fecha DATE NOT NULL,
        efectivo NUMERIC NOT NULL
    ) ON COMMIT DROP;

    TRUNCATE tmp_caja_efectivo_backfill;

    SELECT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'petalops'
          AND table_name = 'pago_metodo'
          AND column_name = 'monto'
    ) INTO has_pago_metodo_monto;

    IF to_regclass('petalops.pago_metodo') IS NOT NULL
       AND to_regclass('petalops.metodo_pago_catalogo') IS NOT NULL
       AND has_pago_metodo_monto THEN
        EXECUTE $sql$
            INSERT INTO tmp_caja_efectivo_backfill (empresa_id, sucursal_id, fecha, efectivo)
            SELECT
                pm.empresa_id,
                p.sucursal_id,
                CAST(p.fecha_pedido AS DATE) AS fecha,
                COALESCE(SUM(pm.monto), 0) AS efectivo
            FROM petalops.pago_metodo pm
            JOIN petalops.metodo_pago_catalogo mpc
              ON mpc.id_metodo_pago = pm.metodo_pago_id
             AND mpc.empresa_id = pm.empresa_id
            JOIN petalops.pedido p
              ON p.id_pedido = pm.pedido_id
             AND p.empresa_id = pm.empresa_id
            LEFT JOIN petalops.estado_pedido ep
              ON ep.id_estado_pedido = p.estado_pedido_id
            WHERE (
                lower(COALESCE(mpc.codigo, '')) = 'efectivo'
                OR lower(COALESCE(mpc.nombre, '')) = 'efectivo'
            )
              AND upper(COALESCE(ep.nombre_estado, '')) NOT IN ('CANCELADO', 'RECHAZADO', 'ANULADO')
            GROUP BY pm.empresa_id, p.sucursal_id, CAST(p.fecha_pedido AS DATE)
        $sql$;
    END IF;

    IF to_regclass('petalops.pago') IS NOT NULL THEN
        IF to_regclass('petalops.pago_metodo') IS NOT NULL AND has_pago_metodo_monto THEN
            legacy_filter := '
              AND NOT EXISTS (
                  SELECT 1
                  FROM petalops.pago_metodo pm
                  WHERE pm.empresa_id = pa.empresa_id
                    AND pm.pedido_id = pa.pedido_id
              )';
        END IF;

        EXECUTE $sql$
            INSERT INTO tmp_caja_efectivo_backfill (empresa_id, sucursal_id, fecha, efectivo)
            SELECT
                pa.empresa_id,
                p.sucursal_id,
                CAST(p.fecha_pedido AS DATE) AS fecha,
                COALESCE(SUM(pa.monto), 0) AS efectivo
            FROM petalops.pago pa
            JOIN petalops.pedido p
              ON p.id_pedido = pa.pedido_id
             AND p.empresa_id = pa.empresa_id
            LEFT JOIN petalops.estado_pedido ep
              ON ep.id_estado_pedido = p.estado_pedido_id
            WHERE COALESCE(pa.metodo_pago, '') ILIKE '%%Efectivo%%'
              AND upper(COALESCE(ep.nombre_estado, '')) NOT IN ('CANCELADO', 'RECHAZADO', 'ANULADO')
        $sql$ || legacy_filter || $sql$
            GROUP BY pa.empresa_id, p.sucursal_id, CAST(p.fecha_pedido AS DATE)
        $sql$;
    END IF;

    WITH efectivo_dia AS (
        SELECT empresa_id, sucursal_id, fecha, SUM(efectivo) AS efectivo
        FROM tmp_caja_efectivo_backfill
        GROUP BY empresa_id, sucursal_id, fecha
    )
    UPDATE petalops.caja c
    SET efectivo = e.efectivo,
        total_efectivo = c.base + e.efectivo - c.gasto,
        nueva_base = c.base + e.efectivo - c.gasto - c.guardado,
        updated_at = CURRENT_TIMESTAMP
    FROM efectivo_dia e
    WHERE c.empresa_id = e.empresa_id
      AND c.sucursal_id = e.sucursal_id
      AND c.fecha = e.fecha;

    WITH efectivo_dia AS (
        SELECT empresa_id, sucursal_id, fecha, SUM(efectivo) AS efectivo
        FROM tmp_caja_efectivo_backfill
        GROUP BY empresa_id, sucursal_id, fecha
    )
    INSERT INTO petalops.caja (
        empresa_id,
        sucursal_id,
        fecha,
        base,
        efectivo,
        gasto,
        total_efectivo,
        guardado,
        nueva_base,
        observacion,
        created_at,
        updated_at
    )
    SELECT
        e.empresa_id,
        e.sucursal_id,
        e.fecha,
        COALESCE(prev.nueva_base, 0) AS base,
        e.efectivo,
        0 AS gasto,
        COALESCE(prev.nueva_base, 0) + e.efectivo AS total_efectivo,
        0 AS guardado,
        COALESCE(prev.nueva_base, 0) + e.efectivo AS nueva_base,
        '',
        CURRENT_TIMESTAMP,
        CURRENT_TIMESTAMP
    FROM efectivo_dia e
    LEFT JOIN LATERAL (
        SELECT c.nueva_base
        FROM petalops.caja c
        WHERE c.empresa_id = e.empresa_id
          AND c.sucursal_id = e.sucursal_id
          AND c.fecha < e.fecha
        ORDER BY c.fecha DESC
        LIMIT 1
    ) prev ON TRUE
    WHERE NOT EXISTS (
        SELECT 1
        FROM petalops.caja c
        WHERE c.empresa_id = e.empresa_id
          AND c.sucursal_id = e.sucursal_id
          AND c.fecha = e.fecha
    );
END $$;

-- Despues de verificar datos y backups, ejecutar manualmente si se decide eliminar legado:
-- DROP TABLE IF EXISTS petalops.caja_gasto;
-- DROP TABLE IF EXISTS petalops.caja_apertura_cierre;
