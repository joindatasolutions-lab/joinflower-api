-- Domicilios operativos solo pueden nacer desde Produccion = ParaEntrega.
-- La fila de entrega puede existir como borrador de datos del pedido, pero no debe
-- quedar enlazada a produccion ni volverse operativa antes de ParaEntrega.

CREATE OR REPLACE FUNCTION petalops._estado_produccion_para_entrega_id()
RETURNS BIGINT
LANGUAGE sql
STABLE
AS $$
    SELECT ep.id_estado_produccion
    FROM petalops.estado_produccion ep
    WHERE lower(replace(replace(coalesce(ep.codigo, ep.nombre), '_', ''), ' ', '')) IN (
        'paraentrega',
        'terminado'
    )
    ORDER BY CASE
        WHEN lower(replace(replace(coalesce(ep.codigo, ep.nombre), '_', ''), ' ', '')) = 'paraentrega' THEN 0
        ELSE 1
    END
    LIMIT 1
$$;

CREATE OR REPLACE FUNCTION petalops._estado_entrega_pendiente_id()
RETURNS BIGINT
LANGUAGE sql
STABLE
AS $$
    SELECT ee.id_estado_entrega
    FROM petalops.estado_entrega ee
    WHERE lower(replace(replace(coalesce(ee.codigo, ee.nombre), '_', ''), ' ', '')) = 'pendiente'
    LIMIT 1
$$;

SELECT setval(
    pg_get_serial_sequence('petalops.estado_entrega', 'id_estado_entrega'),
    COALESCE((SELECT MAX(id_estado_entrega) FROM petalops.estado_entrega), 0),
    true
)
WHERE pg_get_serial_sequence('petalops.estado_entrega', 'id_estado_entrega') IS NOT NULL;

INSERT INTO petalops.estado_entrega (codigo, nombre, orden, created_at)
SELECT 'borrador', 'Borrador', 0, CURRENT_TIMESTAMP
WHERE NOT EXISTS (
    SELECT 1
    FROM petalops.estado_entrega ee
    WHERE lower(replace(replace(coalesce(ee.codigo, ee.nombre), '_', ''), ' ', '')) = 'borrador'
);

CREATE OR REPLACE FUNCTION petalops._estado_entrega_borrador_id()
RETURNS BIGINT
LANGUAGE sql
STABLE
AS $$
    SELECT ee.id_estado_entrega
    FROM petalops.estado_entrega ee
    WHERE lower(replace(replace(coalesce(ee.codigo, ee.nombre), '_', ''), ' ', '')) = 'borrador'
    LIMIT 1
$$;

CREATE OR REPLACE FUNCTION petalops.guard_entrega_produccion_para_entrega()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_estado_produccion BIGINT;
    v_para_entrega BIGINT;
    v_pendiente BIGINT;
BEGIN
    v_pendiente := petalops._estado_entrega_pendiente_id();

    IF NEW.produccionid IS NULL THEN
        IF v_pendiente IS NOT NULL AND NEW.estadoentregaid = v_pendiente THEN
            RAISE EXCEPTION 'Entrega del pedido % bloqueada: Pendiente requiere produccion en ParaEntrega',
                NEW.pedido_id;
        END IF;
        RETURN NEW;
    END IF;

    SELECT p.estado_produccion_id
      INTO v_estado_produccion
    FROM petalops.produccion p
    WHERE p.id_produccion = NEW.produccionid
      AND p.empresa_id = NEW.empresa_id;

    IF v_estado_produccion IS NULL THEN
        RAISE EXCEPTION 'Entrega % no puede enlazarse: produccion % no existe para empresa %',
            NEW.id_entrega, NEW.produccionid, NEW.empresa_id;
    END IF;

    v_para_entrega := petalops._estado_produccion_para_entrega_id();
    IF v_para_entrega IS NULL THEN
        RAISE EXCEPTION 'No existe estado de produccion ParaEntrega/Terminado configurado';
    END IF;

    IF v_estado_produccion <> v_para_entrega THEN
        RAISE EXCEPTION 'Entrega del pedido % bloqueada: produccion % debe estar en ParaEntrega',
            NEW.pedido_id, NEW.produccionid;
    END IF;

    IF NEW.estadoentregaid IS NULL THEN
        NEW.estadoentregaid := petalops._estado_entrega_pendiente_id();
    END IF;

    RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS trg_guard_entrega_produccion_para_entrega ON petalops.entrega;
CREATE TRIGGER trg_guard_entrega_produccion_para_entrega
BEFORE INSERT OR UPDATE OF produccionid, empresa_id, estadoentregaid
ON petalops.entrega
FOR EACH ROW
EXECUTE FUNCTION petalops.guard_entrega_produccion_para_entrega();

CREATE OR REPLACE FUNCTION petalops.sync_entrega_pendiente_al_para_entrega()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_para_entrega BIGINT;
    v_pendiente BIGINT;
    v_entrega_id BIGINT;
BEGIN
    v_para_entrega := petalops._estado_produccion_para_entrega_id();
    IF v_para_entrega IS NULL OR NEW.estado_produccion_id <> v_para_entrega THEN
        RETURN NEW;
    END IF;

    IF OLD.estado_produccion_id IS NOT DISTINCT FROM NEW.estado_produccion_id THEN
        RETURN NEW;
    END IF;

    v_pendiente := petalops._estado_entrega_pendiente_id();
    IF v_pendiente IS NULL THEN
        RAISE EXCEPTION 'No existe estado de entrega Pendiente configurado';
    END IF;

    SELECT e.id_entrega
      INTO v_entrega_id
    FROM petalops.entrega e
    WHERE e.empresa_id = NEW.empresa_id
      AND e.pedido_id = NEW.pedido_id
    ORDER BY e.intentonumero DESC, e.id_entrega DESC
    LIMIT 1;

    IF v_entrega_id IS NULL THEN
        INSERT INTO petalops.entrega (
            empresa_id,
            sucursalid,
            pedido_id,
            produccionid,
            estadoentregaid,
            intentoNumero,
            fechaAsignacion,
            fechaSalida,
            fechaEntregaProgramada,
            createdAt,
            updatedAt
        )
        SELECT
            NEW.empresa_id,
            NEW.sucursal_id,
            NEW.pedido_id,
            NEW.id_produccion,
            v_pendiente,
            1,
            NULL,
            NULL,
            p.fecha_pedido,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        FROM petalops.pedido p
        WHERE p.id_pedido = NEW.pedido_id
          AND p.empresa_id = NEW.empresa_id;
    ELSE
        UPDATE petalops.entrega
           SET produccionid = NEW.id_produccion,
               sucursalid = NEW.sucursal_id,
               estadoentregaid = v_pendiente,
               domiciliarioid = NULL,
               fechaAsignacion = NULL,
               fechaSalida = NULL,
               updatedAt = CURRENT_TIMESTAMP
         WHERE id_entrega = v_entrega_id;
    END IF;

    RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS trg_sync_entrega_pendiente_al_para_entrega ON petalops.produccion;
CREATE TRIGGER trg_sync_entrega_pendiente_al_para_entrega
AFTER UPDATE OF estado_produccion_id
ON petalops.produccion
FOR EACH ROW
EXECUTE FUNCTION petalops.sync_entrega_pendiente_al_para_entrega();

-- Limpieza puntual de inconsistencias existentes: entregas enlazadas a una
-- produccion que aun no esta ParaEntrega vuelven a borrador no operativo.
UPDATE petalops.entrega e
   SET produccionid = NULL,
       estadoentregaid = petalops._estado_entrega_borrador_id(),
       domiciliarioid = NULL,
       fechaAsignacion = NULL,
       fechaSalida = NULL,
       updatedAt = CURRENT_TIMESTAMP
FROM petalops.produccion p
WHERE p.id_produccion = e.produccionid
  AND p.empresa_id = e.empresa_id
  AND p.estado_produccion_id <> petalops._estado_produccion_para_entrega_id();

-- Filas de datos de envio sin produccion todavia no son cola operativa:
-- quedan como Borrador, no Pendiente.
UPDATE petalops.entrega
   SET estadoentregaid = petalops._estado_entrega_borrador_id(),
       updatedAt = CURRENT_TIMESTAMP
 WHERE produccionid IS NULL
   AND estadoentregaid = petalops._estado_entrega_pendiente_id();
