from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import sys

import pandas as pd
from sqlalchemy import func

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import SessionLocal
from app.models.cliente import Cliente
from app.models.estadopedido import EstadoPedido
from app.models.pedido import Pedido
from app.models.pedidodetalle import PedidoDetalle
from app.models.producto import Producto


DEFAULT_EXCEL_PATH = Path("csv/empresas/flora/FLORA_APP_V2.xlsx")
REPORTS_DIR = Path("migrations/reports/migracion_pedidos")


@dataclass
class MigrationSummary:
    filas_leidas: int = 0
    pedidos_creados: int = 0
    detalles_creados: int = 0
    errores_cliente: int = 0
    errores_producto: int = 0
    pedidos_sin_detalle: int = 0


def _sumar_summary(total: MigrationSummary, parcial: MigrationSummary) -> MigrationSummary:
    total.filas_leidas += parcial.filas_leidas
    total.pedidos_creados += parcial.pedidos_creados
    total.detalles_creados += parcial.detalles_creados
    total.errores_cliente += parcial.errores_cliente
    total.errores_producto += parcial.errores_producto
    total.pedidos_sin_detalle += parcial.pedidos_sin_detalle
    return total


def _normalize_text(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip().lower())


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


def _clean_identificacion(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if re.fullmatch(r"\d+\.0", text):
        return text[:-2]
    return text


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
    raise ValueError(f"No se encontro la columna '{expected}' en hoja REGISTRO(S). Columnas: {list(df.columns)}")


def _extract_product_items(productos_cell: object, cantidad_cell: object) -> list[tuple[str, Decimal]]:
    """Parsea formatos tipo '1× Producto A | 2× Producto B'."""
    if pd.isna(productos_cell):
        return []

    text = str(productos_cell).strip()
    if not text:
        return []

    default_qty = _to_decimal(cantidad_cell, Decimal("1"))
    if default_qty <= 0:
        default_qty = Decimal("1")

    items: list[tuple[str, Decimal]] = []
    for part in [p.strip() for p in text.split("|") if p and p.strip()]:
        match = re.match(r"^\s*(\d+(?:[\.,]\d+)?)\s*[x×]\s*(.+)$", part, flags=re.IGNORECASE)
        if match:
            qty_raw = match.group(1).replace(",", ".")
            qty = _to_decimal(qty_raw, Decimal("1"))
            name = match.group(2).strip()
        else:
            qty = default_qty
            name = part

        if name and qty > 0:
            items.append((name, qty))

    return items


def _parse_fecha_pedido(value: object) -> datetime:
    if pd.isna(value):
        return datetime.now(timezone.utc)

    try:
        ts = pd.to_datetime(value)
        if pd.notna(ts):
            dt = ts.to_pydatetime()
            # Si viene sin tz, lo dejamos en UTC para consistencia de migracion.
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt
    except Exception:
        pass

    return datetime.now(timezone.utc)


def migrar_registro_pedidos(
    excel_path: Path,
    empresa_id: int,
    sucursal_id: int,
    apply_changes: bool,
    offset: int = 0,
    batch_size: int | None = None,
    report_suffix: str = "",
) -> MigrationSummary:
    if not excel_path.exists():
        raise FileNotFoundError(f"No existe el archivo Excel: {excel_path}")

    sheet_name = _find_sheet_name(excel_path)
    df = pd.read_excel(excel_path, sheet_name=sheet_name)
    if offset < 0:
        offset = 0
    if batch_size is not None and batch_size > 0:
        df = df.iloc[offset : offset + batch_size].copy()
    else:
        df = df.iloc[offset:].copy()

    col_pedido = _find_column(df, "Pedido")
    col_ident = _find_column(df, "Identificacion", aliases=["Identificación"])
    col_productos = _find_column(df, "Producto", aliases=["Productos"])
    col_cantidad = _find_column(df, "Cantidad")
    col_total = _find_column(df, "Total")
    col_iva = _find_column(df, "Iva", aliases=["IVA"])
    col_fecha = _find_column(df, "Fecha")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    missing_client_rows: list[dict] = []
    missing_product_rows: list[dict] = []

    summary = MigrationSummary(filas_leidas=len(df))

    db = SessionLocal()
    try:
        estado_creado = (
            db.query(EstadoPedido)
            .filter(
                func.lower(EstadoPedido.nombreEstado) == "creado",
                EstadoPedido.activo == True,
            )
            .first()
        )

        next_pedido_id = int(db.query(func.max(Pedido.idPedido)).scalar() or 0) + 1
        next_detalle_id = int(db.query(func.max(PedidoDetalle.idPedidoDetalle)).scalar() or 0) + 1

        for idx, row in df.iterrows():
            pedido_ext = row.get(col_pedido)
            identificacion = _clean_identificacion(row.get(col_ident))

            cliente = None
            if identificacion:
                cliente = (
                    db.query(Cliente)
                    .filter(
                        Cliente.empresaID == empresa_id,
                        Cliente.identificacion == identificacion,
                    )
                    .first()
                )

            if not cliente:
                summary.errores_cliente += 1
                missing_client_rows.append(
                    {
                        "fila_excel": int(idx) + 2,
                        "pedido": "" if pd.isna(pedido_ext) else str(pedido_ext),
                        "identificacion": identificacion,
                        "error": "cliente no encontrado",
                    }
                )
                continue

            fecha_pedido = _parse_fecha_pedido(row.get(col_fecha))

            total_iva = _to_decimal(row.get(col_iva), Decimal("0"))
            total_neto = _to_decimal(row.get(col_total), Decimal("0"))
            total_bruto = total_neto - total_iva
            if total_bruto < 0:
                total_bruto = Decimal("0")

            product_items = _extract_product_items(row.get(col_productos), row.get(col_cantidad))
            detalles_validos: list[dict] = []

            for product_name, qty in product_items:
                product = (
                    db.query(Producto)
                    .filter(
                        Producto.empresaID == empresa_id,
                        func.lower(Producto.nombreProducto) == _normalize_text(product_name),
                    )
                    .first()
                )

                if not product:
                    summary.errores_producto += 1
                    missing_product_rows.append(
                        {
                            "fila_excel": int(idx) + 2,
                            "pedido": "" if pd.isna(pedido_ext) else str(pedido_ext),
                            "producto": product_name,
                            "cantidad": str(qty),
                            "error": "producto no encontrado",
                        }
                    )
                    continue

                precio_unitario = _to_decimal(product.precioBase, Decimal("0"))
                subtotal = precio_unitario * qty

                detalles_validos.append(
                    {
                        "productoID": product.idProducto,
                        "cantidad": qty,
                        "precioUnitario": precio_unitario,
                        "subtotal": subtotal,
                    }
                )

            if len(detalles_validos) == 0:
                summary.pedidos_sin_detalle += 1
            else:
                # Validar que numeroPedido (pedido_ext) no sea NaN ni nulo
                if pedido_ext is None or (isinstance(pedido_ext, float) and pd.isna(pedido_ext)):
                    if 'errores_numero_pedido_rows' not in locals():
                        errores_numero_pedido_rows = []
                    errores_numero_pedido_rows.append({
                        "fila_excel": int(idx) + 2,
                        "pedido": pedido_ext,
                        "identificacion": identificacion,
                        "error": "numeroPedido vacío o NaN"
                    })
                    continue

                # Verificar si ya existe un pedido con la clave única
                existe_pedido = db.query(Pedido).filter(
                    Pedido.empresaID == empresa_id,
                    Pedido.sucursalID == sucursal_id,
                    Pedido.numeroPedido == pedido_ext
                ).first()
                if existe_pedido:
                    # Registrar en reporte de duplicados y omitir
                    if 'duplicados_rows' not in locals():
                        duplicados_rows = []
                    duplicados_rows.append({
                        "fila_excel": int(idx) + 2,
                        "pedido": pedido_ext,
                        "identificacion": identificacion,
                        "error": "pedido duplicado (clave única)"
                    })
                    continue

                pedido = Pedido(
                    idPedido=next_pedido_id,
                    empresaID=empresa_id,
                    sucursalID=sucursal_id,
                    clienteID=cliente.idCliente,
                    fechaPedido=fecha_pedido,
                    fechaPedidoDate=fecha_pedido.date() if hasattr(fecha_pedido, "date") else None,
                    horaPedido=fecha_pedido.time().replace(microsecond=0) if hasattr(fecha_pedido, "time") else None,
                    estadoPedidoID=estado_creado.idEstadoPedido if estado_creado else None,
                    version=1,
                    totalBruto=total_bruto,
                    totalIva=total_iva,
                    totalNeto=total_neto,
                    numeroPedido=pedido_ext,
                    createdAt=datetime.now(timezone.utc),
                )
                if apply_changes:
                    db.add(pedido)

                for det in detalles_validos:
                    detalle = PedidoDetalle(
                        idPedidoDetalle=next_detalle_id,
                        empresaID=empresa_id,
                        sucursalID=sucursal_id,
                        pedidoID=next_pedido_id,
                        productoID=det["productoID"],
                        cantidad=det["cantidad"],
                        precioUnitario=det["precioUnitario"],
                        ivaUnitario=det.get("ivaUnitario", Decimal("0")),
                        subtotal=det["subtotal"],
                    )
                    if apply_changes:
                        db.add(detalle)

                    next_detalle_id += 1
                    summary.detalles_creados += 1

                summary.pedidos_creados += 1
                next_pedido_id += 1

        if apply_changes:
            db.commit()
        else:
            db.rollback()

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    suffix = f"_{report_suffix}" if report_suffix else ""

    pd.DataFrame(missing_client_rows).to_csv(
        REPORTS_DIR / f"errores_clientes_no_encontrados{suffix}.csv",
        index=False,
        encoding="utf-8-sig",
    )

    pd.DataFrame(missing_product_rows).to_csv(
        REPORTS_DIR / f"errores_productos_no_encontrados{suffix}.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # Guardar reporte de errores de numeroPedido si hubo
    if 'errores_numero_pedido_rows' in locals() and errores_numero_pedido_rows:
        pd.DataFrame(errores_numero_pedido_rows).to_csv(
            REPORTS_DIR / f"errores_numero_pedido_invalidos{suffix}.csv",
            index=False,
            encoding="utf-8-sig",
        )

    # Guardar reporte de duplicados si hubo
    if 'duplicados_rows' in locals() and duplicados_rows:
        pd.DataFrame(duplicados_rows).to_csv(
            REPORTS_DIR / f"errores_pedidos_duplicados{suffix}.csv",
            index=False,
            encoding="utf-8-sig",
        )

    resumen_path = REPORTS_DIR / f"resumen_migracion{suffix}.txt"
    resumen_path.write_text(
        "\n".join(
            [
                "MIGRACION PEDIDOS REGISTRO(S)",
                f"Archivo: {excel_path}",
                f"EmpresaID: {empresa_id}",
                f"SucursalID: {sucursal_id}",
                f"Offset: {offset}",
                f"Batch size: {batch_size if batch_size else 'ALL'}",
                f"Filas leidas: {summary.filas_leidas}",
                f"Pedidos creados: {summary.pedidos_creados}",
                f"Detalles creados: {summary.detalles_creados}",
                f"Errores cliente: {summary.errores_cliente}",
                f"Errores producto: {summary.errores_producto}",
                f"Pedidos sin detalle valido: {summary.pedidos_sin_detalle}",
                f"Modo: {'APPLY' if apply_changes else 'DRY-RUN'}",
            ]
        ),
        encoding="utf-8",
    )

    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Migrar hoja REGISTRO(S) a Pedido/PedidoDetalle")
    parser.add_argument("--excel", type=Path, default=DEFAULT_EXCEL_PATH, help="Ruta del Excel")
    parser.add_argument("--empresa-id", type=int, default=3, help="Empresa destino")
    parser.add_argument("--sucursal-id", type=int, default=1, help="Sucursal destino")
    parser.add_argument("--offset", type=int, default=0, help="Fila inicial (0-based) para migrar")
    parser.add_argument("--batch-size", type=int, default=None, help="Cantidad de filas a migrar por lote")
    parser.add_argument(
        "--run-all-batches",
        action="store_true",
        help="Procesa lotes consecutivos hasta terminar el archivo (requiere batch-size).",
    )
    parser.add_argument("--apply", action="store_true", help="Aplica cambios en base de datos")
    return parser


def main() -> None:
    args = _build_parser().parse_args()

    if args.run_all_batches:
        if not args.batch_size or args.batch_size <= 0:
            raise ValueError("--run-all-batches requiere --batch-size > 0")

        # Calcula total de filas del sheet para cortar el loop correctamente.
        sheet_name = _find_sheet_name(args.excel)
        total_filas = len(pd.read_excel(args.excel, sheet_name=sheet_name))
        current_offset = max(args.offset, 0)
        lote = 1
        total = MigrationSummary()

        while current_offset < total_filas:
            summary_lote = migrar_registro_pedidos(
                excel_path=args.excel,
                empresa_id=args.empresa_id,
                sucursal_id=args.sucursal_id,
                apply_changes=args.apply,
                offset=current_offset,
                batch_size=args.batch_size,
                report_suffix=f"lote_{lote}",
            )

            _sumar_summary(total, summary_lote)

            print(
                f"Lote {lote}: offset={current_offset}, filas={summary_lote.filas_leidas}, "
                f"pedidos={summary_lote.pedidos_creados}, detalles={summary_lote.detalles_creados}"
            )

            if summary_lote.filas_leidas == 0:
                break

            current_offset += summary_lote.filas_leidas
            lote += 1

        summary = total
    else:
        summary = migrar_registro_pedidos(
            excel_path=args.excel,
            empresa_id=args.empresa_id,
            sucursal_id=args.sucursal_id,
            apply_changes=args.apply,
            offset=args.offset,
            batch_size=args.batch_size,
            report_suffix="single_run",
        )

    print("\n=== MIGRACION PEDIDOS REGISTRO(S) ===")
    print(f"empresaID: {args.empresa_id}")
    print(f"pedidos_creados: {summary.pedidos_creados}")
    print(f"detalles_creados: {summary.detalles_creados}")
    print(f"errores_cliente: {summary.errores_cliente}")
    print(f"errores_producto: {summary.errores_producto}")
    print(f"pedidos_sin_detalle: {summary.pedidos_sin_detalle}")
    print(f"reportes: {REPORTS_DIR}")
    print("modo:", "APPLY" if args.apply else "DRY-RUN")


if __name__ == "__main__":
    main()
