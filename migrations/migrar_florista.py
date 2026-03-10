from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
import sys

import pandas as pd
from sqlalchemy import func

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import SessionLocal
from app.models.florista import Florista


DEFAULT_EXCEL_PATH = Path("csv/empresas/flora/FLORA_APP_V2.xlsx")
REPORTS_DIR = Path("migrations/reports/migracion_florista")


@dataclass
class Summary:
    total_leidos: int = 0
    total_insertados: int = 0
    total_duplicados: int = 0
    total_errores: int = 0


def normalizar_texto(valor: object) -> str:
    if valor is None or pd.isna(valor):
        return ""
    return str(valor).strip().lower()


def _sheet_florista_name(excel_path: Path) -> str:
    xls = pd.ExcelFile(excel_path)
    for name in xls.sheet_names:
        if normalizar_texto(name) in {"florista", "floristas"}:
            return name
    raise ValueError("No se encontro hoja FLORISTA/FLORISTAS en el Excel")


def _find_column(df: pd.DataFrame, expected: str, aliases: list[str] | None = None) -> str:
    aliases = aliases or []
    targets = {normalizar_texto(expected), *[normalizar_texto(a) for a in aliases]}
    for col in df.columns:
        if normalizar_texto(col) in targets:
            return col
    raise ValueError(f"No se encontro columna '{expected}'. Columnas detectadas: {list(df.columns)}")


def _parse_int(valor: object, default: int = 0) -> int:
    if valor is None or pd.isna(valor):
        return default
    text = str(valor).strip()
    text = re.sub(r"[^0-9-]", "", text)
    if text == "":
        return default
    try:
        return int(text)
    except Exception:
        return default


def _disponible_bool(valor: object) -> bool:
    txt = normalizar_texto(valor)
    return txt in {"si", "sí", "s", "true", "1", "activo", "disponible"}


def migrar_florista(excel_path: Path, empresa_id: int, sucursal_id: int) -> Summary:
    if not excel_path.exists():
        raise FileNotFoundError(f"No existe el archivo Excel: {excel_path}")

    sheet_name = _sheet_florista_name(excel_path)
    df = pd.read_excel(excel_path, sheet_name=sheet_name)

    col_id_empleado = _find_column(df, "ID Empleado", aliases=["idempleado", "codigo", "id"])
    col_nombre = _find_column(df, "Nombre", aliases=["florista", "empleado"])
    col_disponibilidad = _find_column(df, "Disponibilidad", aliases=["estado", "disponible"])
    col_carga_hoy = _find_column(df, "CargaHoy", aliases=["carga", "capacidad", "cupo"])

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    insertados: list[dict] = []
    duplicados: list[dict] = []
    errores: list[dict] = []

    summary = Summary(total_leidos=len(df))

    db = SessionLocal()
    try:
        next_id = int(db.query(func.max(Florista.idFlorista)).scalar() or 0) + 1

        existentes = (
            db.query(Florista)
            .filter(
                Florista.empresaID == empresa_id,
                Florista.sucursalID == sucursal_id,
            )
            .all()
        )
        key_existentes = {
            (fl.empresaID, fl.sucursalID, normalizar_texto(fl.nombre))
            for fl in existentes
        }

        for idx, row in df.iterrows():
            nombre = normalizar_texto(row.get(col_nombre))
            id_empleado = normalizar_texto(row.get(col_id_empleado))
            disponible = _disponible_bool(row.get(col_disponibilidad))
            carga_hoy = _parse_int(row.get(col_carga_hoy), default=0)

            # Campos obligatorios segun modelo.
            if not nombre:
                summary.total_errores += 1
                errores.append(
                    {
                        "fila_excel": int(idx) + 2,
                        "id_empleado": id_empleado,
                        "nombre": nombre,
                        "error": "nombre obligatorio vacio",
                    }
                )
                continue

            if carga_hoy < 0:
                summary.total_errores += 1
                errores.append(
                    {
                        "fila_excel": int(idx) + 2,
                        "id_empleado": id_empleado,
                        "nombre": nombre,
                        "error": "capacidad/carga invalida",
                    }
                )
                continue

            key = (empresa_id, sucursal_id, nombre)
            if key in key_existentes:
                summary.total_duplicados += 1
                duplicados.append(
                    {
                        "fila_excel": int(idx) + 2,
                        "id_empleado": id_empleado,
                        "nombre": nombre,
                        "motivo": "duplicado empresaID+sucursalID+nombre",
                    }
                )
                continue

            # Mapeo al modelo SQLAlchemy existente.
            florista = Florista(
                idFlorista=next_id,
                empresaID=empresa_id,
                sucursalID=sucursal_id,
                nombre=nombre,
                capacidadDiaria=max(carga_hoy, 1),
                trabajosSimultaneosPermitidos=1,
                estado="activo" if disponible else "inactivo",
                activo=disponible,
                especialidades=(f"id_empleado:{id_empleado}" if id_empleado else None),
                createdAt=datetime.now(timezone.utc),
            )
            db.add(florista)

            insertados.append(
                {
                    "fila_excel": int(idx) + 2,
                    "idFlorista": next_id,
                    "empresaID": empresa_id,
                    "sucursalID": sucursal_id,
                    "nombre": nombre,
                    "estado": florista.estado,
                    "activo": int(bool(florista.activo)),
                    "capacidadDiaria": florista.capacidadDiaria,
                }
            )

            key_existentes.add(key)
            next_id += 1
            summary.total_insertados += 1

        db.commit()

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    pd.DataFrame(insertados).to_csv(REPORTS_DIR / "floristas_insertados.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(duplicados).to_csv(REPORTS_DIR / "floristas_duplicados.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(errores).to_csv(REPORTS_DIR / "floristas_error.csv", index=False, encoding="utf-8-sig")

    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Migrar hoja FLORISTA(S) a tabla Florista")
    parser.add_argument("--excel", type=Path, default=DEFAULT_EXCEL_PATH, help="Ruta del Excel")
    parser.add_argument("--empresa-id", type=int, required=True, help="Empresa destino")
    parser.add_argument("--sucursal-id", type=int, default=1, help="Sucursal destino")
    return parser


def main() -> None:
    args = _build_parser().parse_args()

    summary = migrar_florista(
        excel_path=args.excel,
        empresa_id=args.empresa_id,
        sucursal_id=args.sucursal_id,
    )

    print("\n=== MIGRACION FLORISTA ===")
    print(f"Total registros leidos: {summary.total_leidos}")
    print(f"Total registros insertados: {summary.total_insertados}")
    print(f"Total registros duplicados: {summary.total_duplicados}")
    print(f"Total errores: {summary.total_errores}")
    print(f"Reportes: {REPORTS_DIR}")


if __name__ == "__main__":
    main()
