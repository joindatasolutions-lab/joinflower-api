from __future__ import annotations

import argparse
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import sys

import pandas as pd
from sqlalchemy import and_, func

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import SessionLocal
from app.models.barrio import Barrio
from app.models.cliente import Cliente
from app.models.entrega import Entrega
from app.models.empresa import Empresa  # noqa: F401
from app.models.pedido import Pedido
from app.models.empleado import Empleado

DEFAULT_EXCEL_PATH = Path("csv/empresas/flora/FLORA_APP_V2.xlsx")
REPORTS_DIR = Path("migrations/reports/backfill_entregas")


@dataclass
class BackfillSummary:
    filas_leidas: int = 0
    entregas_creadas: int = 0
    pedidos_sin_match: int = 0
    clientes_no_encontrados: int = 0
    barrios_no_encontrados: int = 0


def _normalize_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return re.sub(r"\s+", " ", str(value).strip().lower())


def _clean_identificacion(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if re.fullmatch(r"\d+\.0", text):
        return text[:-2]
    return text


def _to_decimal(value: object, default: Decimal = Decimal("0")) -> Decimal:
    if pd.isna(value):
        return default
    raw = str(value).strip().replace("$", "").replace(",", "")
    if raw == "":
        return default
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return default


def _find_sheet_name(excel_path: Path) -> str:
    xls = pd.ExcelFile(excel_path)
    for name in xls.sheet_names:
        if name.strip().lower() in {"registro", "registros"}:
            return name
    raise ValueError("No se encontro hoja REGISTRO/REGISTROS en el Excel")


def _find_column(df: pd.DataFrame, expected: str, aliases: list[str] | None = None) -> str:
    aliases = aliases or []
    targets = {_normalize_text(expected), *[_normalize_text(a) for a in aliases]}
    for col in df.columns:
        if _normalize_text(col) in targets:
            return col
    raise ValueError(f"No se encontro la columna '{expected}' en hoja REGISTRO(S).")


def _find_optional_column(df: pd.DataFrame, expected: str, aliases: list[str] | None = None) -> str | None:
    aliases = aliases or []
    targets = {_normalize_text(expected), *[_normalize_text(a) for a in aliases]}
    for col in df.columns:
        if _normalize_text(col) in targets:
            return col
    return None


def _parse_datetime(value: object, fallback_now: bool = False) -> datetime | None:
    if pd.isna(value):
        return datetime.now(timezone.utc) if fallback_now else None
    try:
        ts = pd.to_datetime(value)
        if pd.notna(ts):
            dt = ts.to_pydatetime()
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt
    except Exception:
        return datetime.now(timezone.utc) if fallback_now else None
    return datetime.now(timezone.utc) if fallback_now else None


def _combine_fecha_hora(fecha_value: object, hora_value: object) -> datetime | None:
    dt_fecha = _parse_datetime(fecha_value, fallback_now=False)
    if dt_fecha is None:
        return None

    if pd.isna(hora_value):
        return dt_fecha

    try:
        dt_hora = pd.to_datetime(hora_value)
        if pd.notna(dt_hora):
            h = dt_hora.to_pydatetime().time().replace(microsecond=0)
            return dt_fecha.replace(hour=h.hour, minute=h.minute, second=h.second, microsecond=0)
    except Exception:
        pass

    hora_txt = str(hora_value).strip()
    m = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$", hora_txt)
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2))
        ss = int(m.group(3) or 0)
        return dt_fecha.replace(hour=hh, minute=mm, second=ss, microsecond=0)

    return dt_fecha


def _is_pickup_in_store(barrio_nombre: str | None) -> bool:
    if not barrio_nombre:
        return False
    normalized = _normalize_text(barrio_nombre)
    return normalized in {
        "entrega en tienda",
        "entrega en tienda - entrega en tienda",
        "recoger en tienda",
        "recoge en tienda",
        "tienda",
        "flora",
    }


def backfill_entregas(
    excel_path: Path,
    empresa_id: int,
    apply_changes: bool,
    estado_entrega_id: int = 1,
) -> BackfillSummary:
    if not excel_path.exists():
        raise FileNotFoundError(f"No existe el archivo Excel: {excel_path}")

    sheet_name = _find_sheet_name(excel_path)
    df = pd.read_excel(excel_path, sheet_name=sheet_name)

    col_ident = _find_column(df, "Identificacion", aliases=["Identificación"])
    col_fecha = _find_column(df, "Fecha")
    col_total = _find_column(df, "Total")
    col_destinatario = _find_optional_column(df, "Destinatario")
    col_barrio = _find_optional_column(df, "Barrio")
    col_direccion = _find_optional_column(df, "Direccion", aliases=["Dirección"])
    col_tel_destino = _find_optional_column(df, "telefonoDestino", aliases=["TelefonoDestino", "TelDestino"])
    col_fecha_entrega = _find_optional_column(df, "Fecha de Entrega")
    col_hora_entrega = _find_optional_column(df, "Hora de Entrega")
    col_mensaje = _find_optional_column(df, "Mensaje")
    col_observaciones = _find_optional_column(df, "Observaciones")
    col_firma = _find_optional_column(df, "NombreFirma")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    summary = BackfillSummary(filas_leidas=len(df))
    missing_client_rows: list[dict] = []
    missing_pedido_rows: list[dict] = []
    missing_barrio_rows: list[dict] = []

    db = SessionLocal()
    try:
        next_entrega_id = int(db.query(func.max(Entrega.idEntrega)).scalar() or 0) + 1

        barrios = db.query(Barrio).filter(Barrio.empresaID == empresa_id).all()
        barrio_map = {_normalize_text(b.nombreBarrio): b for b in barrios}

        clientes = db.query(Cliente.idCliente, Cliente.identificacion).filter(Cliente.empresaID == empresa_id).all()
        cliente_by_ident = {str(ident): cid for cid, ident in clientes if ident}

        pedidos_sin_entrega = (
            db.query(Pedido.idPedido, Pedido.clienteID, Pedido.fechaPedidoDate, Pedido.totalNeto)
            .outerjoin(
                Entrega,
                and_(
                    Entrega.pedidoID == Pedido.idPedido,
                    Entrega.empresaID == Pedido.empresaID,
                ),
            )
            .filter(
                Pedido.empresaID == empresa_id,
                Entrega.idEntrega.is_(None),
            )
            .order_by(Pedido.idPedido.asc())
            .all()
        )

        pedidos_idx_exact: dict[tuple[int, object, str], deque[int]] = defaultdict(deque)
        pedidos_idx_fallback: dict[tuple[int, object], deque[int]] = defaultdict(deque)
        for pid, cliente_id, fecha_date, total_neto in pedidos_sin_entrega:
            total_key = str(total_neto if total_neto is not None else Decimal("0"))
            pedidos_idx_exact[(int(cliente_id), fecha_date, total_key)].append(int(pid))
            pedidos_idx_fallback[(int(cliente_id), fecha_date)].append(int(pid))

        used_pedidos: set[int] = set()

        for idx, row in df.iterrows():
            identificacion = _clean_identificacion(row.get(col_ident))
            if not identificacion:
                summary.clientes_no_encontrados += 1
                missing_client_rows.append(
                    {
                        "fila_excel": int(idx) + 2,
                        "identificacion": "",
                        "error": "identificacion vacia",
                    }
                )
                continue

            cliente_id = cliente_by_ident.get(identificacion)
            if not cliente_id:
                summary.clientes_no_encontrados += 1
                missing_client_rows.append(
                    {
                        "fila_excel": int(idx) + 2,
                        "identificacion": identificacion,
                        "error": "cliente no encontrado",
                    }
                )
                continue

            fecha_pedido = _parse_datetime(row.get(col_fecha), fallback_now=False)
            if fecha_pedido is None:
                summary.pedidos_sin_match += 1
                missing_pedido_rows.append(
                    {
                        "fila_excel": int(idx) + 2,
                        "identificacion": identificacion,
                        "motivo": "fecha invalida",
                    }
                )
                continue

            total_neto = _to_decimal(row.get(col_total), Decimal("0"))
            fecha_date = fecha_pedido.date() if hasattr(fecha_pedido, "date") else None
            total_key = str(total_neto)

            pedido_id = None
            exact_queue = pedidos_idx_exact.get((int(cliente_id), fecha_date, total_key))
            while exact_queue and exact_queue[0] in used_pedidos:
                exact_queue.popleft()
            if exact_queue:
                pedido_id = exact_queue.popleft()

            if pedido_id is None:
                fb_queue = pedidos_idx_fallback.get((int(cliente_id), fecha_date))
                while fb_queue and fb_queue[0] in used_pedidos:
                    fb_queue.popleft()
                if fb_queue:
                    pedido_id = fb_queue.popleft()

            if pedido_id is None:
                summary.pedidos_sin_match += 1
                missing_pedido_rows.append(
                    {
                        "fila_excel": int(idx) + 2,
                        "identificacion": identificacion,
                        "fecha": str(fecha_date),
                        "total": str(total_neto),
                        "motivo": "pedido sin match",
                    }
                )
                continue

            used_pedidos.add(pedido_id)

            destinatario = str(row.get(col_destinatario)).strip() if col_destinatario and not pd.isna(row.get(col_destinatario)) else None
            direccion = str(row.get(col_direccion)).strip() if col_direccion and not pd.isna(row.get(col_direccion)) else None
            telefono_destino = str(row.get(col_tel_destino)).strip() if col_tel_destino and not pd.isna(row.get(col_tel_destino)) else None
            barrio_nombre = str(row.get(col_barrio)).strip() if col_barrio and not pd.isna(row.get(col_barrio)) else None
            mensaje = str(row.get(col_mensaje)).strip() if col_mensaje and not pd.isna(row.get(col_mensaje)) else None
            observaciones = str(row.get(col_observaciones)).strip() if col_observaciones and not pd.isna(row.get(col_observaciones)) else None
            firma = str(row.get(col_firma)).strip() if col_firma and not pd.isna(row.get(col_firma)) else None

            is_pickup = _is_pickup_in_store(barrio_nombre)
            barrio_nombre_canonico = "Recoger en Tienda" if is_pickup else barrio_nombre

            barrio_id = None
            if barrio_nombre_canonico:
                barrio = barrio_map.get(_normalize_text(barrio_nombre_canonico))
                if barrio:
                    barrio_id = barrio.idBarrio
                else:
                    summary.barrios_no_encontrados += 1
                    missing_barrio_rows.append(
                        {
                            "fila_excel": int(idx) + 2,
                            "pedido_id": pedido_id,
                            "barrio": barrio_nombre_canonico,
                            "error": "barrio no encontrado",
                        }
                    )

            fecha_entrega = _combine_fecha_hora(
                row.get(col_fecha_entrega) if col_fecha_entrega else None,
                row.get(col_hora_entrega) if col_hora_entrega else None,
            )

            if not any([destinatario, direccion, telefono_destino, barrio_nombre, mensaje, observaciones, fecha_entrega]):
                continue

            if is_pickup:
                tipo_entrega = "Recoger en Tienda"
            elif direccion or barrio_nombre_canonico:
                tipo_entrega = "DOMICILIO"
            else:
                tipo_entrega = None

            entrega = Entrega(
                idEntrega=next_entrega_id,
                empresaID=empresa_id,
                pedidoID=pedido_id,
                estadoEntregaID=estado_entrega_id,
                tipoEntrega=tipo_entrega,
                destinatario=destinatario,
                telefonoDestino=telefono_destino,
                direccion=direccion,
                barrioID=barrio_id,
                barrioNombre=barrio_nombre_canonico,
                mensaje=mensaje,
                firma=firma,
                observacionGeneral=observaciones,
                fechaEntrega=fecha_entrega,
                createdAt=datetime.now(timezone.utc),
            )

            if apply_changes:
                db.add(entrega)

            next_entrega_id += 1
            summary.entregas_creadas += 1

        if apply_changes:
            db.commit()
        else:
            db.rollback()

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    mode = "apply" if apply_changes else "dry_run"
    pd.DataFrame(missing_client_rows).to_csv(
        REPORTS_DIR / f"clientes_no_encontrados_{mode}.csv",
        index=False,
        encoding="utf-8-sig",
    )
    pd.DataFrame(missing_pedido_rows).to_csv(
        REPORTS_DIR / f"pedidos_sin_match_{mode}.csv",
        index=False,
        encoding="utf-8-sig",
    )
    pd.DataFrame(missing_barrio_rows).to_csv(
        REPORTS_DIR / f"barrios_no_encontrados_{mode}.csv",
        index=False,
        encoding="utf-8-sig",
    )

    resumen_path = REPORTS_DIR / f"resumen_backfill_{mode}.txt"
    resumen_path.write_text(
        "\n".join(
            [
                "BACKFILL ENTREGAS DESDE REGISTRO(S)",
                f"Archivo: {excel_path}",
                f"EmpresaID: {empresa_id}",
                f"Filas leidas: {summary.filas_leidas}",
                f"Entregas creadas: {summary.entregas_creadas}",
                f"Pedidos sin match: {summary.pedidos_sin_match}",
                f"Clientes no encontrados: {summary.clientes_no_encontrados}",
                f"Barrios no encontrados: {summary.barrios_no_encontrados}",
                f"Modo: {mode.upper()}",
            ]
        ),
        encoding="utf-8",
    )

    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill Entrega desde hoja REGISTRO(S)")
    parser.add_argument("--excel", type=Path, default=DEFAULT_EXCEL_PATH, help="Ruta del Excel")
    parser.add_argument("--empresa-id", type=int, default=3, help="Empresa destino")
    parser.add_argument("--estado-entrega-id", type=int, default=1, help="EstadoEntregaID para nuevos registros")
    parser.add_argument("--apply", action="store_true", help="Aplica cambios en base de datos")
    return parser


def main() -> None:
    args = _build_parser().parse_args()

    summary = backfill_entregas(
        excel_path=args.excel,
        empresa_id=args.empresa_id,
        apply_changes=args.apply,
        estado_entrega_id=args.estado_entrega_id,
    )

    print("\n=== BACKFILL ENTREGAS REGISTRO(S) ===")
    print(f"empresaID: {args.empresa_id}")
    print(f"entregas_creadas: {summary.entregas_creadas}")
    print(f"pedidos_sin_match: {summary.pedidos_sin_match}")
    print(f"clientes_no_encontrados: {summary.clientes_no_encontrados}")
    print(f"barrios_no_encontrados: {summary.barrios_no_encontrados}")
    print(f"reportes: {REPORTS_DIR}")
    print("modo:", "APPLY" if args.apply else "DRY-RUN")


if __name__ == "__main__":
    main()
