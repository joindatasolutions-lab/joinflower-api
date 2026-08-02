"""Backfill seguro de produccion_historial para cambios historicos de estado.

No cambia estados, no crea produccion, no toca pedidos ni entregas. Solo inserta
registros sinteticos en produccion_historial para producciones no pendientes que
no tienen historial explicito de cambio/cancelacion/terminacion.
"""

import argparse
import os

import psycopg2
from psycopg2.extras import RealDictCursor

def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Variable de entorno requerida no definida: {name}")
    return value

def _config() -> dict:
    return {
        "host": _required_env("PGHOST"),
        "user": _required_env("PGUSER"),
        "password": _required_env("PGPASSWORD"),
        "dbname": _required_env("PGDATABASE"),
        "port": int(os.getenv("PGPORT", "5432")),
    }


SELECT_SQL = """
SELECT pr.id_produccion, pr.empresa_id, pr.sucursal_id, pr.empleado_id,
       ep.codigo, ep.nombre, pr.created_at, pr.updated_at, pr.fecha_inicio, pr.fecha_finalizacion
FROM petalops.produccion pr
JOIN petalops.estado_produccion ep ON ep.id_estado_produccion = pr.estado_produccion_id
WHERE pr.empresa_id = %(empresa_id)s
  AND ep.codigo <> 'pendiente'
  AND NOT EXISTS (
    SELECT 1
    FROM petalops.produccion_historial h
    WHERE h.produccion_id = pr.id_produccion
      AND h.empresa_id = pr.empresa_id
      AND (
        h.motivo ILIKE '%%estado%%'
        OR h.motivo ILIKE '%%cancel%%'
        OR h.motivo ILIKE '%%termin%%'
      )
  )
ORDER BY pr.id_produccion
"""

INSERT_SQL = """
INSERT INTO petalops.produccion_historial (
    empresa_id,
    sucursal_id,
    produccion_id,
    florista_anterior_id,
    florista_nuevo_id,
    fecha_cambio,
    motivo,
    usuariocambio
)
SELECT
    pr.empresa_id,
    pr.sucursal_id,
    pr.id_produccion,
    pr.empleado_id,
    pr.empleado_id,
    COALESCE(pr.updated_at, pr.fecha_finalizacion, pr.fecha_inicio, pr.created_at, CURRENT_TIMESTAMP),
    'Backfill historico estado produccion: ' || ep.nombre,
    'system.backfill'
FROM petalops.produccion pr
JOIN petalops.estado_produccion ep ON ep.id_estado_produccion = pr.estado_produccion_id
WHERE pr.empresa_id = %(empresa_id)s
  AND ep.codigo <> 'pendiente'
  AND NOT EXISTS (
    SELECT 1
    FROM petalops.produccion_historial h
    WHERE h.produccion_id = pr.id_produccion
      AND h.empresa_id = pr.empresa_id
      AND (
        h.motivo ILIKE '%%estado%%'
        OR h.motivo ILIKE '%%cancel%%'
        OR h.motivo ILIKE '%%termin%%'
      )
  )
RETURNING produccion_id
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--empresa-id", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    conn = psycopg2.connect(**_config())
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(SELECT_SQL, {"empresa_id": int(args.empresa_id)})
                rows = cur.fetchall()
                print(f"empresa_id={args.empresa_id} producciones_sin_historial_estado={len(rows)}")
                print("sample=", rows[:10])
                if not args.apply:
                    conn.rollback()
                    return 0
                cur.execute(INSERT_SQL, {"empresa_id": int(args.empresa_id)})
                inserted = [row["produccion_id"] for row in cur.fetchall()]
                print(f"insertados={len(inserted)}")
                print("produccion_ids=", inserted)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())