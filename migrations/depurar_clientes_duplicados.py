from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys

from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import SessionLocal


@dataclass
class DedupSummary:
    grupos_duplicados: int = 0
    filas_sobrantes: int = 0
    filas_eliminadas: int = 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Depurar clientes duplicados por empresaID + identificacion")
    parser.add_argument("--empresa-id", type=int, required=True, help="ID de empresa a depurar")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Aplica eliminaciones. Sin este flag, solo muestra diagnostico (dry-run).",
    )
    parser.add_argument(
        "--keep",
        choices=["oldest", "newest"],
        default="oldest",
        help="Cual registro conservar por cada identificacion duplicada.",
    )
    return parser


def deduplicar_clientes(empresa_id: int, apply_changes: bool, keep: str) -> DedupSummary:
    summary = DedupSummary()

    # Normaliza identificacion para comparar: trim + remueve sufijo .0 comun de Excel.
    norm_ident = "CASE WHEN TRIM(identificacion) REGEXP '^[0-9]+\\\\.0$' THEN LEFT(TRIM(identificacion), LENGTH(TRIM(identificacion)) - 2) ELSE TRIM(identificacion) END"

    metric_sql = text(
        f"""
        SELECT COUNT(*) AS grupos_duplicados, COALESCE(SUM(cnt) - COUNT(*), 0) AS filas_sobrantes
        FROM (
            SELECT {norm_ident} AS ident_norm, COUNT(*) AS cnt
            FROM Cliente
            WHERE empresaID = :empresa_id
              AND identificacion IS NOT NULL
              AND TRIM(identificacion) <> ''
            GROUP BY ident_norm
            HAVING COUNT(*) > 1
        ) d
        """
    )

    # Marca filas a eliminar con ROW_NUMBER sobre cada identificacion normalizada.
    order_col = "idCliente ASC" if keep == "oldest" else "idCliente DESC"
    rows_to_delete_sql = text(
        f"""
        SELECT idCliente
        FROM (
            SELECT
                idCliente,
                ROW_NUMBER() OVER (
                    PARTITION BY {norm_ident}
                    ORDER BY {order_col}
                ) AS rn
            FROM Cliente
            WHERE empresaID = :empresa_id
              AND identificacion IS NOT NULL
              AND TRIM(identificacion) <> ''
        ) t
        WHERE t.rn > 1
        """
    )

    db = SessionLocal()
    try:
        row = db.execute(metric_sql, {"empresa_id": empresa_id}).mappings().first()
        if row:
            summary.grupos_duplicados = int(row["grupos_duplicados"] or 0)
            summary.filas_sobrantes = int(row["filas_sobrantes"] or 0)

        ids_to_delete = [r[0] for r in db.execute(rows_to_delete_sql, {"empresa_id": empresa_id}).all()]

        if apply_changes and ids_to_delete:
            for cid in ids_to_delete:
                db.execute(
                    text("DELETE FROM Cliente WHERE idCliente = :id"),
                    {"id": cid},
                )
            db.commit()
            summary.filas_eliminadas = len(ids_to_delete)
        else:
            db.rollback()
            summary.filas_eliminadas = 0

        return summary
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    args = _build_parser().parse_args()

    summary = deduplicar_clientes(
        empresa_id=args.empresa_id,
        apply_changes=args.apply,
        keep=args.keep,
    )

    print("\n=== DEPURACION CLIENTES DUPLICADOS ===")
    print(f"Empresa ID: {args.empresa_id}")
    print(f"Estrategia keep: {args.keep}")
    print(f"Grupos duplicados: {summary.grupos_duplicados}")
    print(f"Filas sobrantes detectadas: {summary.filas_sobrantes}")
    print(f"Filas eliminadas: {summary.filas_eliminadas}")
    print("Modo:", "APPLY" if args.apply else "DRY-RUN")


if __name__ == "__main__":
    main()
