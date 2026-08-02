"""Backfill seguro de domicilio_auditoria para entregas historicas sin auditoria.

No cambia estados, no asigna domiciliarios, no crea entregas ni toca pedidos o
produccion. Solo inserta un evento sintetico CREAR_ENTREGA_HISTORICA para cada
entrega sin auditoria propia.
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


ENSURE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS petalops.domicilio_auditoria (
  id_audit BIGSERIAL PRIMARY KEY,
  empresa_id BIGINT NOT NULL,
  sucursal_id BIGINT,
  pedido_id BIGINT NOT NULL,
  entrega_id BIGINT NOT NULL,
  actor_user_id BIGINT,
  actor_login VARCHAR(120) NOT NULL,
  domiciliario_id BIGINT,
  accion VARCHAR(60) NOT NULL,
  estado_anterior VARCHAR(40),
  estado_nuevo VARCHAR(40),
  detalle_json TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_domicilio_auditoria_empresa_fecha
  ON petalops.domicilio_auditoria (empresa_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_domicilio_auditoria_pedido
  ON petalops.domicilio_auditoria (empresa_id, pedido_id);
"""

SELECT_SQL = """
SELECT e.id_entrega, e.empresa_id, e.sucursalid, e.pedido_id, e.domiciliarioid,
       ee.codigo AS estado_codigo, e.createdat, e.updatedat
FROM petalops.entrega e
LEFT JOIN petalops.estado_entrega ee ON ee.id_estado_entrega = e.estadoentregaid
WHERE e.empresa_id = %(empresa_id)s
  AND NOT EXISTS (
    SELECT 1
    FROM petalops.domicilio_auditoria da
    WHERE da.empresa_id = e.empresa_id
      AND da.entrega_id = e.id_entrega
  )
ORDER BY e.id_entrega
"""

INSERT_SQL = """
INSERT INTO petalops.domicilio_auditoria (
    empresa_id,
    sucursal_id,
    pedido_id,
    entrega_id,
    actor_user_id,
    actor_login,
    domiciliario_id,
    accion,
    estado_anterior,
    estado_nuevo,
    detalle_json,
    created_at
)
SELECT
    e.empresa_id,
    e.sucursalid,
    e.pedido_id,
    e.id_entrega,
    NULL,
    'system.backfill',
    e.domiciliarioid,
    'CREAR_ENTREGA_HISTORICA',
    NULL,
    COALESCE(ee.codigo, e.estadoentregaid::text),
    '{"source":"backfill_domicilio_auditoria_historica"}',
    COALESCE(e.createdat, e.updatedat, CURRENT_TIMESTAMP)
FROM petalops.entrega e
LEFT JOIN petalops.estado_entrega ee ON ee.id_estado_entrega = e.estadoentregaid
WHERE e.empresa_id = %(empresa_id)s
  AND NOT EXISTS (
    SELECT 1
    FROM petalops.domicilio_auditoria da
    WHERE da.empresa_id = e.empresa_id
      AND da.entrega_id = e.id_entrega
  )
RETURNING entrega_id
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--empresa-id", type=int, required=True)
    parser.add_argument("--apply", action="store_true", help="Inserta auditoria historica. Sin esto solo muestra conteo.")
    args = parser.parse_args()

    conn = psycopg2.connect(**_config())
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(ENSURE_TABLE_SQL)
            cur.execute(SELECT_SQL, {"empresa_id": args.empresa_id})
            rows = cur.fetchall()
            print(f"Entregas sin auditoria para empresa {args.empresa_id}: {len(rows)}")
            for row in rows[:20]:
                print(dict(row))
            if len(rows) > 20:
                print(f"... {len(rows) - 20} mas")

            if not args.apply:
                conn.rollback()
                print("Dry-run: no se insertaron registros.")
                return 0

            cur.execute(INSERT_SQL, {"empresa_id": args.empresa_id})
            inserted = cur.fetchall()
            conn.commit()
            print(f"Insertados en domicilio_auditoria: {len(inserted)}")
            return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())