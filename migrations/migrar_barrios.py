from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import re
import sys

import pandas as pd
from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import SessionLocal


DEFAULT_EXCEL_PATH = Path("csv/empresas/flora/FLORA_APP_V2.xlsx")
REPORTS_DIR = Path("migrations/reports/migracion_barrios")


@dataclass
class Summary:
    total_barrios_leidos: int = 0
    total_barrios_insertados: int = 0
    total_barrios_duplicados: int = 0
    total_registros_actualizados: int = 0


def normalizar_texto(value: object) -> str:
    """Normaliza texto para evitar duplicados por mayusculas/espacios."""
    if value is None or pd.isna(value):
        return ""
    return str(value).strip().lower()


def _sheet_barrio_name(excel_path: Path) -> str:
    xls = pd.ExcelFile(excel_path)
    for name in xls.sheet_names:
        if normalizar_texto(name) in {"barrio", "barrios"}:
            return name
    raise ValueError("No se encontro hoja BARRIO/BARRIOS en el Excel")


def _find_column(df: pd.DataFrame, expected: str, aliases: list[str] | None = None) -> str:
    aliases = aliases or []
    targets = {normalizar_texto(expected), *[normalizar_texto(a) for a in aliases]}
    for col in df.columns:
        if normalizar_texto(col) in targets:
            return col
    raise ValueError(f"No se encontro columna '{expected}'. Columnas detectadas: {list(df.columns)}")


def _parse_zona_id(value: object) -> int:
    txt = normalizar_texto(value)
    if not txt:
        return 1
    m = re.search(r"(\d+)", txt)
    return int(m.group(1)) if m else 1


def _parse_costo(value: object) -> Decimal:
    if value is None or pd.isna(value):
        return Decimal("0")
    txt = str(value).strip().replace("$", "").replace(",", "")
    try:
        return Decimal(txt)
    except Exception:
        return Decimal("0")


def _table_exists(db, table_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = :table_name
            LIMIT 1
            """
        ),
        {"table_name": table_name},
    ).first()
    return row is not None


def _table_columns(db, table_name: str) -> set[str]:
    rows = db.execute(
        text(
            """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = :table_name
            """
        ),
        {"table_name": table_name},
    ).all()
    return {r[0] for r in rows}


def _table_pk(db, table_name: str) -> str | None:
    row = db.execute(
        text(
            """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = :table_name
              AND CONSTRAINT_NAME = 'PRIMARY'
            ORDER BY ORDINAL_POSITION
            LIMIT 1
            """
        ),
        {"table_name": table_name},
    ).first()
    return row[0] if row else None


def migrar_barrios(excel_path: Path, empresa_id: int) -> Summary:
    if not excel_path.exists():
        raise FileNotFoundError(f"No existe el archivo Excel: {excel_path}")

    sheet_name = _sheet_barrio_name(excel_path)
    df = pd.read_excel(excel_path, sheet_name=sheet_name)

    col_nombre = _find_column(df, "Nombre", aliases=["Barrio", "Nombre Barrio"])
    col_costo = _find_column(df, "Valor Domicilio", aliases=["Costo", "Costo Domicilio", "Valor Domicilio\n"])
    col_zona = _find_column(df, "Zona")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    insertados: list[dict] = []
    duplicados: list[dict] = []
    no_encontrados: list[dict] = []
    resumen = Summary(total_barrios_leidos=len(df))

    db = SessionLocal()
    try:
        # Carga barrios ya existentes para empresa (normalizados).
        existing_rows = db.execute(
            text(
                """
                SELECT idBarrio, nombreBarrio
                FROM Barrio
                WHERE empresaID = :empresa_id
                """
            ),
            {"empresa_id": empresa_id},
        ).mappings().all()

        barrios_map: dict[str, int] = {
            normalizar_texto(r["nombreBarrio"]): int(r["idBarrio"])
            for r in existing_rows
            if normalizar_texto(r["nombreBarrio"])
        }

        for idx, row in df.iterrows():
            nombre_norm = normalizar_texto(row.get(col_nombre))
            if not nombre_norm:
                duplicados.append(
                    {
                        "fila_excel": int(idx) + 2,
                        "nombre_original": "",
                        "nombre_normalizado": "",
                        "motivo": "nombre vacio",
                    }
                )
                continue

            if nombre_norm in barrios_map:
                duplicados.append(
                    {
                        "fila_excel": int(idx) + 2,
                        "nombre_original": str(row.get(col_nombre)),
                        "nombre_normalizado": nombre_norm,
                        "motivo": "duplicado empresaID+nombreBarrio",
                    }
                )
                continue

            zona_id = _parse_zona_id(row.get(col_zona))
            costo = _parse_costo(row.get(col_costo))

            db.execute(
                text(
                    """
                    INSERT INTO Barrio (
                        empresaID,
                        sucursalID,
                        zonaID,
                        nombreBarrio,
                        costoDomicilio,
                        activo,
                        createdAt
                    ) VALUES (
                        :empresa_id,
                        :sucursal_id,
                        :zona_id,
                        :nombre_barrio,
                        :costo,
                        :activo,
                        :created_at
                    )
                    """
                ),
                {
                    "empresa_id": empresa_id,
                    "sucursal_id": 1,
                    "zona_id": zona_id,
                    "nombre_barrio": nombre_norm,
                    "costo": costo,
                    "activo": 1,
                    "created_at": datetime.now(timezone.utc),
                },
            )

            new_id = db.execute(text("SELECT LAST_INSERT_ID()" )).scalar()
            if new_id:
                barrios_map[nombre_norm] = int(new_id)

            insertados.append(
                {
                    "fila_excel": int(idx) + 2,
                    "idBarrio": int(new_id) if new_id else None,
                    "empresaID": empresa_id,
                    "nombreBarrio": nombre_norm,
                    "zonaID": zona_id,
                    "costoDomicilio": str(costo),
                }
            )

        resumen.total_barrios_insertados = len(insertados)
        resumen.total_barrios_duplicados = len(duplicados)

        # Actualizar tablas relacionadas por nombre de barrio -> barrioID.
        # Prioridad de tablas solicitadas por requerimiento.
        candidate_tables = ["Cliente", "Pedido", "Domicilio", "Entrega"]
        for table_name in candidate_tables:
            if not _table_exists(db, table_name):
                continue

            columns = _table_columns(db, table_name)
            if "barrioID" not in columns:
                continue

            name_col = None
            for c in ["barrioNombre", "barrio", "nombreBarrio"]:
                if c in columns:
                    name_col = c
                    break

            if not name_col:
                continue

            pk_col = _table_pk(db, table_name)
            if not pk_col:
                continue

            # Registrar no encontrados por nombre de barrio (con empresa filtrada si existe columna).
            empresa_filter = " AND t.empresaID = :empresa_id " if "empresaID" in columns else ""
            nf_sql = text(
                f"""
                SELECT t.{pk_col} AS registro_id, t.{name_col} AS barrio_original
                FROM {table_name} t
                LEFT JOIN Barrio b
                  ON b.empresaID = :empresa_id
                 AND LOWER(TRIM(t.{name_col})) = b.nombreBarrio
                WHERE t.{name_col} IS NOT NULL
                  AND TRIM(t.{name_col}) <> ''
                  {empresa_filter}
                  AND b.idBarrio IS NULL
                """
            )
            for nf in db.execute(nf_sql, {"empresa_id": empresa_id}).mappings().all():
                no_encontrados.append(
                    {
                        "tabla": table_name,
                        "registro_id": nf["registro_id"],
                        "barrio_original": nf["barrio_original"],
                        "barrio_normalizado": normalizar_texto(nf["barrio_original"]),
                    }
                )

            # Actualizar barrioID cuando exista match por nombre normalizado.
            upd_sql = text(
                f"""
                UPDATE {table_name} t
                JOIN Barrio b
                  ON b.empresaID = :empresa_id
                 AND LOWER(TRIM(t.{name_col})) = b.nombreBarrio
                SET t.barrioID = b.idBarrio
                WHERE t.{name_col} IS NOT NULL
                  AND TRIM(t.{name_col}) <> ''
                  {empresa_filter}
                  AND (t.barrioID IS NULL OR t.barrioID <> b.idBarrio)
                """
            )
            result = db.execute(upd_sql, {"empresa_id": empresa_id})
            resumen.total_registros_actualizados += int(result.rowcount or 0)

        db.commit()

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    pd.DataFrame(insertados).to_csv(REPORTS_DIR / "barrios_insertados.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(duplicados).to_csv(REPORTS_DIR / "barrios_duplicados.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(no_encontrados).to_csv(REPORTS_DIR / "barrios_no_encontrados.csv", index=False, encoding="utf-8-sig")

    return resumen


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Migrar hoja BARRIO(S) a tabla Barrio y actualizar referencias")
    parser.add_argument("--excel", type=Path, default=DEFAULT_EXCEL_PATH, help="Ruta del Excel")
    parser.add_argument("--empresa-id", type=int, required=True, help="Empresa destino")
    return parser


def main() -> None:
    args = _build_parser().parse_args()

    resumen = migrar_barrios(excel_path=args.excel, empresa_id=args.empresa_id)

    print("\n=== MIGRACION BARRIOS ===")
    print(f"Total barrios leidos: {resumen.total_barrios_leidos}")
    print(f"Total barrios insertados: {resumen.total_barrios_insertados}")
    print(f"Total barrios duplicados: {resumen.total_barrios_duplicados}")
    print(f"Total registros actualizados: {resumen.total_registros_actualizados}")
    print(f"Reportes: {REPORTS_DIR}")


if __name__ == "__main__":
    main()
