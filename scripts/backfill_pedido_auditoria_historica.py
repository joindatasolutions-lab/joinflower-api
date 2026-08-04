"""Backfill seguro de pedido_auditoria para pedidos historicos sin auditoria.

No cambia estados, no crea produccion, no toca entregas ni pagos. Solo inserta un
evento sintetico CREAR_PEDIDO_HISTORICO para pedidos que no tienen auditoria.
"""

import argparse
import os
from pathlib import Path

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
SELECT p.id_pedido, p.empresa_id, p.sucursal_id, p.estado_pedido_id, p.created_at
FROM petalops.pedido p
WHERE p.empresa_id = %(empresa_id)s
  AND NOT EXISTS (
    SELECT 1
    FROM petalops.pedido_auditoria pa
    WHERE pa.pedido_id = p.id_pedido
      AND pa.empresa_id = p.empresa_id
  )
ORDER BY p.id_pedido
"""

INSERT_SQL = """
INSERT INTO petalops.pedido_auditoria (
    empresa_id,
    sucursal_id,
    pedido_id,
    actor_user_id,
    actor_login,
    accion,
    estado_origen_id,
    estado_destino_id,
    detalle_json,
    created_at
)
SELECT
    p.empresa_id,
    p.sucursal_id,
    p.id_pedido,
    NULL,
    'system.backfill',
    'CREAR_PEDIDO_HISTORICO',
    NULL,
    p.estado_pedido_id,
    '{"source":"backfill_pedido_auditoria_historica"}',
    COALESCE(p.created_at, CURRENT_TIMESTAMP)
FROM petalops.pedido p
WHERE p.empresa_id = %(empresa_id)s
  AND NOT EXISTS (
    SELECT 1
    FROM petalops.pedido_auditoria pa
    WHERE pa.pedido_id = p.id_pedido
      AND pa.empresa_id = p.empresa_id
  )
RETURNING pedido_id
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--empresa-id", type=int, required=True)
    parser.add_argument("--apply", action="store_true", help="Inserta auditoria historica. Sin esto solo muestra conteo.")
    args = parser.parse_args()

    conn = psycopg2.connect(**_config())
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(SELECT_SQL, {"empresa_id": int(args.empresa_id)})
                rows = cur.fetchall()
                print(f"empresa_id={args.empresa_id} pedidos_sin_auditoria={len(rows)}")
                print("sample=", rows[:10])

                if not args.apply:
                    conn.rollback()
                    return 0

                cur.execute(INSERT_SQL, {"empresa_id": int(args.empresa_id)})
                inserted = [row["pedido_id"] for row in cur.fetchall()]
                print(f"insertados={len(inserted)}")
                print("pedido_ids=", inserted)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())