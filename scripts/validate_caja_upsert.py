import sys
from pathlib import Path

from sqlalchemy import create_engine, text

sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.inspect_caja_tables import build_url  # noqa: E402


def main() -> None:
    engine = create_engine(build_url(), pool_pre_ping=True)
    conn = engine.connect()
    transaction = conn.begin()
    try:
        row = conn.execute(
            text(
                """
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
                    usuario_id,
                    updated_at
                )
                VALUES (
                    :empresa_id,
                    :sucursal_id,
                    :fecha,
                    :base,
                    :efectivo,
                    :gasto,
                    :total_efectivo,
                    :guardado,
                    :nueva_base,
                    :observacion,
                    :usuario_id,
                    CURRENT_TIMESTAMP
                )
                ON CONFLICT (empresa_id, sucursal_id, fecha)
                DO UPDATE SET
                    base = EXCLUDED.base,
                    efectivo = EXCLUDED.efectivo,
                    gasto = EXCLUDED.gasto,
                    total_efectivo = EXCLUDED.total_efectivo,
                    guardado = EXCLUDED.guardado,
                    nueva_base = EXCLUDED.nueva_base,
                    observacion = EXCLUDED.observacion,
                    usuario_id = EXCLUDED.usuario_id,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id_caja,
                          empresa_id,
                          sucursal_id,
                          fecha
                """
            ),
            {
                "empresa_id": 1,
                "sucursal_id": 1,
                "fecha": "2099-12-31",
                "base": 100000,
                "efectivo": 70000,
                "gasto": 15000,
                "total_efectivo": 155000,
                "guardado": 40000,
                "nueva_base": 115000,
                "observacion": "rollback test",
                "usuario_id": None,
            },
        ).mappings().first()
        print(dict(row))
    finally:
        transaction.rollback()
        conn.close()


if __name__ == "__main__":
    main()
