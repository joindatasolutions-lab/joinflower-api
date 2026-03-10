from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
import unicodedata

import pandas as pd


EXCEL_PATH = Path("csv/empresas/flora/FLORA_APP_V2.xlsx")
REQUIRED_SHEETS = ["CLIENTES", "CATALOGO", "REGISTROS", "PRODUCCION", "DOMICILIOS"]
REPORTS_DIR = Path("migrations/reports")


def _normalize_text(value: object) -> str:
    """Normaliza texto para comparaciones tolerantes a acentos, espacios y mayusculas."""
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = "".join(
        char for char in unicodedata.normalize("NFKD", text) if not unicodedata.combining(char)
    )
    return re.sub(r"[^a-z0-9]", "", text)


def _normalize_order_id(value: object) -> str:
    """Normaliza identificadores de pedido para comparar entre hojas."""
    if pd.isna(value):
        return ""
    text = str(value).strip()

    # Evita inconsistencias comunes de Excel: 1001 vs 1001.0
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]

    return text


def _find_column(df: pd.DataFrame, sheet_name: str, expected: str, aliases: list[str] | None = None) -> str:
    aliases = aliases or []
    targets = [_normalize_text(expected), *[_normalize_text(alias) for alias in aliases]]

    for column in df.columns:
        normalized = _normalize_text(column)
        if normalized in targets:
            return column

    aliases_text = ", ".join([expected, *aliases])
    raise ValueError(
        f"No se encontro una columna valida para '{aliases_text}' en la hoja '{sheet_name}'. "
        f"Columnas detectadas: {list(df.columns)}"
    )


def _extract_product_names(products_cell: object) -> list[str]:
    """Extrae nombres de producto desde strings tipo '1× Producto A | 2x Producto B'."""
    if pd.isna(products_cell):
        return []

    text = str(products_cell).strip()
    if not text:
        return []

    parts = [part.strip() for part in text.split("|") if part and part.strip()]
    product_names: list[str] = []

    for part in parts:
        clean_name = re.sub(r"^\s*\d+\s*[x×]\s*", "", part, flags=re.IGNORECASE).strip()
        if clean_name:
            product_names.append(clean_name)

    return product_names


def _resolve_sheet_names(xls: pd.ExcelFile) -> dict[str, str]:
    """Mapea nombres de hoja requeridos a nombres reales del archivo Excel."""
    available_by_norm = {_normalize_text(name): name for name in xls.sheet_names}
    resolved: dict[str, str] = {}

    for required in REQUIRED_SHEETS:
        key = _normalize_text(required)
        if key not in available_by_norm:
            raise ValueError(
                f"Falta la hoja requerida '{required}'. Hojas disponibles: {xls.sheet_names}"
            )
        resolved[required] = available_by_norm[key]

    return resolved


def _build_run_dir() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = REPORTS_DIR / f"validacion_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _export_dataframe(df: pd.DataFrame, file_path: Path) -> None:
    """Exporta un dataframe a CSV en UTF-8 si tiene datos."""
    if not df.empty:
        df.to_csv(file_path, index=False, encoding="utf-8-sig")


def validar_excel() -> None:
    excel_file = EXCEL_PATH

    if not excel_file.exists():
        print(f"ERROR: No existe el archivo Excel en '{excel_file}'.")
        return

    print(f"Leyendo Excel: {excel_file}")
    run_dir = _build_run_dir()

    xls = pd.ExcelFile(excel_file)
    try:
        resolved_sheets = _resolve_sheet_names(xls)
    except ValueError as error:
        print(f"ERROR: {error}")
        return

    clientes_df = pd.read_excel(excel_file, sheet_name=resolved_sheets["CLIENTES"])
    catalogo_df = pd.read_excel(excel_file, sheet_name=resolved_sheets["CATALOGO"])
    registros_df = pd.read_excel(excel_file, sheet_name=resolved_sheets["REGISTROS"])
    produccion_df = pd.read_excel(excel_file, sheet_name=resolved_sheets["PRODUCCION"])
    domicilios_df = pd.read_excel(excel_file, sheet_name=resolved_sheets["DOMICILIOS"])

    try:
        col_pedido_reg = _find_column(registros_df, "REGISTROS", "Pedido")
        col_producto_reg = _find_column(registros_df, "REGISTROS", "Producto")
        col_ident_clientes = _find_column(clientes_df, "CLIENTES", "Identificacion", aliases=["Identificación"])
        col_producto_catalogo = _find_column(
            catalogo_df,
            "CATALOGO",
            "Producto",
            aliases=["name", "nombre", "producto_nombre"],
        )
        col_pedido_produccion = _find_column(
            produccion_df,
            "PRODUCCION",
            "N°Pedido",
            aliases=["NoPedido", "NPedido", "NumeroPedido", "NroPedido"],
        )
        col_pedido_domicilios = _find_column(
            domicilios_df,
            "DOMICILIOS",
            "N°Pedido",
            aliases=["NoPedido", "NPedido", "NumeroPedido", "NroPedido"],
        )
    except ValueError as error:
        print(f"ERROR: {error}")
        return

    print("\n--- 1) VALIDAR PEDIDOS DUPLICADOS (REGISTROS) ---")
    pedidos_series = registros_df[col_pedido_reg].dropna().map(_normalize_order_id)
    pedidos_series = pedidos_series[pedidos_series != ""]

    duplicados = (
        pedidos_series[pedidos_series.duplicated(keep=False)]
        .value_counts()
        .rename_axis("Pedido")
        .reset_index(name="Repeticiones")
    )
    _export_dataframe(duplicados, run_dir / "01_pedidos_duplicados.csv")

    if duplicados.empty:
        print("OK: No hay pedidos duplicados.")
    else:
        print("Pedidos duplicados encontrados:")
        print(duplicados.to_string(index=False))

    print("\n--- 2) VALIDAR CLIENTES SIN IDENTIFICACION (CLIENTES) ---")
    mask_ident_nula = clientes_df[col_ident_clientes].isna()
    clientes_sin_ident = clientes_df[mask_ident_nula]
    _export_dataframe(clientes_sin_ident, run_dir / "02_clientes_sin_identificacion.csv")

    if clientes_sin_ident.empty:
        print("OK: No hay clientes sin identificacion.")
    else:
        print("Filas con identificacion nula:")
        print(clientes_sin_ident.to_string(index=False))

    print("\n--- 3) VALIDAR PRODUCTOS DEL PEDIDO vs CATALOGO ---")
    productos_catalogo = {
        _normalize_text(value)
        for value in catalogo_df[col_producto_catalogo].dropna()
        if str(value).strip()
    }

    productos_no_catalogo: set[str] = set()

    for cell in registros_df[col_producto_reg].dropna():
        for product_name in _extract_product_names(cell):
            if _normalize_text(product_name) not in productos_catalogo:
                productos_no_catalogo.add(product_name)

    if not productos_no_catalogo:
        print("OK: Todos los productos de REGISTROS existen en CATALOGO.")
    else:
        print("Productos inexistentes en CATALOGO:")
        for product in sorted(productos_no_catalogo):
            print(f"- {product}")

    productos_no_catalogo_df = pd.DataFrame(
        {"Producto": sorted(productos_no_catalogo)}
    )
    _export_dataframe(productos_no_catalogo_df, run_dir / "03_productos_no_catalogo.csv")

    print("\n--- 4) VALIDAR RELACION PRODUCCION -> REGISTROS ---")
    pedidos_registros = {
        _normalize_order_id(value)
        for value in registros_df[col_pedido_reg].dropna()
        if _normalize_order_id(value)
    }
    pedidos_produccion = {
        _normalize_order_id(value)
        for value in produccion_df[col_pedido_produccion].dropna()
        if _normalize_order_id(value)
    }

    pedidos_produccion_inexistentes = sorted(pedidos_produccion - pedidos_registros)
    pedidos_produccion_inexistentes_df = pd.DataFrame(
        {"N°Pedido": pedidos_produccion_inexistentes}
    )
    _export_dataframe(
        pedidos_produccion_inexistentes_df,
        run_dir / "04_produccion_pedidos_inexistentes.csv",
    )

    if not pedidos_produccion_inexistentes:
        print("OK: Todos los N°Pedido de PRODUCCION existen en REGISTROS.")
    else:
        print("Pedidos de PRODUCCION que no existen en REGISTROS:")
        for pedido in pedidos_produccion_inexistentes:
            print(f"- {pedido}")

    print("\n--- 5) VALIDAR RELACION DOMICILIOS -> REGISTROS ---")
    pedidos_domicilios = {
        _normalize_order_id(value)
        for value in domicilios_df[col_pedido_domicilios].dropna()
        if _normalize_order_id(value)
    }

    pedidos_domicilios_inexistentes = sorted(pedidos_domicilios - pedidos_registros)
    pedidos_domicilios_inexistentes_df = pd.DataFrame(
        {"N°Pedido": pedidos_domicilios_inexistentes}
    )
    _export_dataframe(
        pedidos_domicilios_inexistentes_df,
        run_dir / "05_domicilios_pedidos_inexistentes.csv",
    )

    if not pedidos_domicilios_inexistentes:
        print("OK: Todos los N°Pedido de DOMICILIOS existen en REGISTROS.")
    else:
        print("Pedidos de DOMICILIOS que no existen en REGISTROS:")
        for pedido in pedidos_domicilios_inexistentes:
            print(f"- {pedido}")

    print("\n--- 6) RESUMEN FINAL ---")
    total_pedidos = registros_df[col_pedido_reg].dropna().map(_normalize_order_id)
    total_pedidos = int((total_pedidos != "").sum())

    print(f"Total pedidos: {total_pedidos}")
    print(f"Total clientes: {len(clientes_df)}")
    print(f"Total productos: {len(catalogo_df)}")
    print(f"Total domicilios: {len(domicilios_df)}")
    print(f"Total registros produccion: {len(produccion_df)}")

    resumen = [
        "RESUMEN VALIDACION EXCEL FLORISTERIA",
        f"Archivo: {excel_file}",
        f"Fecha ejecucion: {datetime.now().isoformat(timespec='seconds')}",
        "",
        f"Total pedidos: {total_pedidos}",
        f"Total clientes: {len(clientes_df)}",
        f"Total productos: {len(catalogo_df)}",
        f"Total domicilios: {len(domicilios_df)}",
        f"Total registros produccion: {len(produccion_df)}",
        "",
        f"Pedidos duplicados: {len(duplicados)}",
        f"Clientes sin identificacion: {len(clientes_sin_ident)}",
        f"Productos no catalogo: {len(productos_no_catalogo_df)}",
        f"Pedidos produccion inexistentes: {len(pedidos_produccion_inexistentes_df)}",
        f"Pedidos domicilios inexistentes: {len(pedidos_domicilios_inexistentes_df)}",
    ]
    (run_dir / "resumen_validacion.txt").write_text("\n".join(resumen), encoding="utf-8")

    print("\nReportes generados en:", run_dir)


if __name__ == "__main__":
    validar_excel()
