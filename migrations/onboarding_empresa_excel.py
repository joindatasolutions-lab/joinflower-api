from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import sys
import unicodedata

import pandas as pd
from sqlalchemy import func, text
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import SessionLocal
from app.models.categoria import Categoria
from app.models.cliente import Cliente
from app.models.empresa import Empresa
from app.models.producto import Producto


DEFAULT_EXCEL_PATH = Path("csv/empresas/flora/FLORA_APP_V2.xlsx")
REQUIRED_SHEETS = ["CLIENTES", "CATALOGO"]


@dataclass
class OnboardingSummary:
    empresa_creada: int = 0
    categorias_creadas: int = 0
    productos_insertados: int = 0
    productos_omitidos_por_duplicado: int = 0
    productos_sin_imagen: int = 0
    clientes_creados: int = 0
    clientes_omitidos: int = 0
    clientes_ignorados_duplicado: int = 0
    clientes_ignorados_nit_flora: int = 0
    clientes_telefono_invalido: int = 0
    filas_cliente_sin_identificacion: int = 0


def normalizar_telefono(numero: object) -> str:
    """Normaliza telefonos a ultimos 10 digitos, removiendo prefijos e indicadores."""
    if pd.isna(numero):
        return ""

    raw = str(numero).strip()
    if not raw:
        return ""

    # Limpia caracteres no numericos, luego elimina prefijo pais si aplica.
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("57"):
        digits = digits[2:]

    if len(digits) < 10:
        return ""

    return digits[-10:]


def _normalizar_identificacion(value: object) -> str:
    if pd.isna(value):
        return ""
    return re.sub(r"\D", "", str(value))


def _limpiar_identificacion(value: object) -> str:
    if pd.isna(value):
        return ""

    ident = str(value).strip()
    if re.fullmatch(r"\d+\.0", ident):
        ident = ident[:-2]

    return ident


def _normalize_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = "".join(
        char for char in unicodedata.normalize("NFKD", text) if not unicodedata.combining(char)
    )
    return re.sub(r"[^a-z0-9]", "", text)


def _find_column(df: pd.DataFrame, expected: str, aliases: list[str] | None = None) -> str:
    aliases = aliases or []
    targets = {_normalize_text(expected), *(_normalize_text(alias) for alias in aliases)}

    for column in df.columns:
        if _normalize_text(column) in targets:
            return column

    raise ValueError(
        f"No se encontro la columna '{expected}' (aliases: {aliases}) en: {list(df.columns)}"
    )


def _try_find_column(df: pd.DataFrame, expected: str, aliases: list[str] | None = None) -> str | None:
    try:
        return _find_column(df, expected, aliases=aliases)
    except ValueError:
        return None


def _resolve_required_sheets(excel: pd.ExcelFile) -> dict[str, str]:
    available = {_normalize_text(name): name for name in excel.sheet_names}
    resolved: dict[str, str] = {}

    for required in REQUIRED_SHEETS:
        key = _normalize_text(required)
        if key not in available:
            raise ValueError(f"Falta hoja requerida '{required}'. Disponibles: {excel.sheet_names}")
        resolved[required] = available[key]

    return resolved


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


def _to_bool(value: object, default: bool = True) -> bool:
    if pd.isna(value):
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "t", "si", "s", "yes", "y", "activo"}:
        return True
    if text in {"0", "false", "f", "no", "n", "inactivo"}:
        return False
    return default


def _next_bigint_id(db: Session, model, id_column) -> int:
    current_max = db.query(func.max(id_column)).scalar()
    return int(current_max or 0) + 1


def _build_id_counters(db: Session) -> dict[str, int]:
    """Carga una sola vez los siguientes IDs para evitar consultas por cada fila."""
    return {
        "categoria": _next_bigint_id(db, Categoria, Categoria.idCategoria),
        "producto": _next_bigint_id(db, Producto, Producto.idProducto),
        "cliente": _next_bigint_id(db, Cliente, Cliente.idCliente),
    }


def _table_has_column(db: Session, table_name: str, column_name: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT 1
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = :table_name
              AND COLUMN_NAME = :column_name
            LIMIT 1
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    ).first()
    return row is not None


def _ensure_unique_empresa_value(db: Session, field: str, base_value: str, empresa_id: int) -> str:
    value = base_value.strip() or f"empresa_{empresa_id}"
    exists = db.execute(
        text(f"SELECT 1 FROM Empresa WHERE {field} = :value LIMIT 1"),
        {"value": value},
    ).first()
    if not exists:
        return value

    suffix = f"-{empresa_id}"
    return f"{value}{suffix}"


def _ensure_empresa(
    db: Session,
    empresa_id: int,
    summary: OnboardingSummary,
    apply_changes: bool,
    empresa_nombre: str | None,
    empresa_nit: str | None,
    empresa_nombre_comercial: str | None,
) -> None:
    exists = db.execute(
        text("SELECT idEmpresa FROM Empresa WHERE idEmpresa = :id LIMIT 1"),
        {"id": empresa_id},
    ).first()
    if exists:
        if apply_changes and empresa_nombre_comercial and empresa_nombre_comercial.strip():
            db.execute(
                text("UPDATE Empresa SET nombreComercial = :nombre WHERE idEmpresa = :id"),
                {"id": empresa_id, "nombre": empresa_nombre_comercial.strip()},
            )
        if apply_changes:
            db.execute(
                text("UPDATE Empresa SET planID = 1 WHERE idEmpresa = :id"),
                {"id": empresa_id},
            )
        return

    nombre_base = (empresa_nombre or f"Empresa {empresa_id}").strip()
    nit_base = (empresa_nit or f"ONB-{empresa_id}").strip()

    nombre_final = _ensure_unique_empresa_value(db, "nombreEmpresa", nombre_base, empresa_id)
    nit_final = _ensure_unique_empresa_value(db, "nit", nit_base, empresa_id)
    nombre_comercial_final = (empresa_nombre_comercial or nombre_final).strip()

    if apply_changes:
        db.execute(
            text(
                """
                INSERT INTO Empresa (
                    idEmpresa,
                    nombreEmpresa,
                    nit,
                    estado,
                    createdAt,
                    updatedAt,
                    nombreComercial,
                    planID
                )
                VALUES (:id, :nombre, :nit, :estado, NOW(), NOW(), :nombre_comercial, :plan_id)
                """
            ),
            {
                "id": empresa_id,
                "nombre": nombre_final,
                "nit": nit_final,
                "estado": 1,
                "nombre_comercial": nombre_comercial_final,
                "plan_id": 1,
            },
        )
        # Necesario para satisfacer FK antes de insertar categorias/productos.
        db.flush()

    summary.empresa_creada += 1


def _build_categoria_cache(db: Session, empresa_id: int) -> dict[str, Categoria]:
    categorias = db.query(Categoria).filter(Categoria.empresaID == empresa_id).all()
    return {_normalize_text(c.nombreCategoria): c for c in categorias if c.nombreCategoria}


def _get_or_create_categoria(
    db: Session,
    empresa_id: int,
    categoria_nombre: str,
    cache: dict[str, Categoria],
    summary: OnboardingSummary,
    apply_changes: bool,
    id_counters: dict[str, int],
) -> Categoria:
    normalized = _normalize_text(categoria_nombre)
    if normalized in cache:
        return cache[normalized]

    next_id = id_counters["categoria"]
    id_counters["categoria"] += 1
    categoria = Categoria(
        idCategoria=next_id,
        empresaID=empresa_id,
        nombreCategoria=categoria_nombre,
        descripcion="",
        orden=1,
        activo=True,
        createdAt=datetime.now(timezone.utc),
    )
    if apply_changes:
        db.add(categoria)
        db.flush()

    cache[normalized] = categoria
    summary.categorias_creadas += 1
    return categoria


def _onboard_catalogo(
    db: Session,
    empresa_id: int,
    catalogo_df: pd.DataFrame,
    summary: OnboardingSummary,
    apply_changes: bool,
    id_counters: dict[str, int],
) -> None:

    col_id = _find_column(catalogo_df, "id", aliases=["ID", "codigo", "CODIGO"])
    # Usar 'name' como principal y 'Producto', 'nombre', etc. como alias
    col_producto = _find_column(catalogo_df, "name", aliases=["Producto", "nombre", "producto_nombre"])
    col_precio = _find_column(catalogo_df, "price", aliases=["precio", "precioBase", " price"])
    col_image = _find_column(catalogo_df, "image", aliases=["img", "imagen", "imagenUrl"])
    col_cantidad = _try_find_column(catalogo_df, "cantidad", aliases=["stock", "cantidadDisponible"])

    col_categoria = None
    for guess in ["categoria", "categoriaNombre", "Categoria"]:
        try:
            col_categoria = _find_column(catalogo_df, guess)
            break
        except ValueError:
            continue

    col_activo = None
    for guess in ["activo", "estado"]:
        try:
            col_activo = _find_column(catalogo_df, guess)
            break
        except ValueError:
            continue

    categorias_cache = _build_categoria_cache(db, empresa_id)
    has_stock_column = _table_has_column(db, "Producto", "stock")

    existing_products = db.query(Producto).filter(Producto.empresaID == empresa_id).all()
    existing_names = {
        _normalize_text(prod.nombreProducto): prod
        for prod in existing_products
        if prod.nombreProducto
    }

    for _, row in catalogo_df.iterrows():
        raw_nombre_producto = row.get(col_producto, "")
        if pd.isna(raw_nombre_producto):
            continue

        nombre_producto = str(raw_nombre_producto).strip()
        if not nombre_producto or _normalize_text(nombre_producto) == "nan":
            continue

        normalized_name = _normalize_text(nombre_producto)
        if normalized_name in existing_names:
            summary.productos_omitidos_por_duplicado += 1
            continue

        raw_image = row.get(col_image)
        image_url = "" if pd.isna(raw_image) else str(raw_image).strip()
        if not image_url or _normalize_text(image_url) == "nan":
            image_url = None
            summary.productos_sin_imagen += 1

        stock_value = None
        if col_cantidad:
            raw_cantidad = row.get(col_cantidad)
            stock_value = None if pd.isna(raw_cantidad) else int(_to_decimal(raw_cantidad, Decimal("0")))

        categoria_nombre = "General"
        if col_categoria:
            raw_categoria_value = row.get(col_categoria, "")
            raw_categoria = "" if pd.isna(raw_categoria_value) else str(raw_categoria_value).strip()
            if raw_categoria and _normalize_text(raw_categoria) != "nan":
                categoria_nombre = raw_categoria

        categoria = _get_or_create_categoria(
            db,
            empresa_id,
            categoria_nombre,
            categorias_cache,
            summary,
            apply_changes,
            id_counters,
        )


        next_id = id_counters["producto"]
        id_counters["producto"] += 1
        id_excel = row.get(col_id)
        if pd.isna(id_excel) or str(id_excel).strip() == "":
            codigo_producto = f"FLR-3-{next_id}"
        else:
            codigo_producto = f"FLR-3-{id_excel}"
        producto = Producto(
            idProducto=next_id,
            empresaID=empresa_id,
            codigoProducto=codigo_producto,
            categoriaID=categoria.idCategoria,
            nombreProducto=nombre_producto,
            descripcion="",
            precioBase=_to_decimal(row.get(col_precio)),
            porcentajeIva=Decimal("0"),
            ivaIncluido=False,
            tiempoBaseProduccionMin=30,
            nivelComplejidad="MEDIA",
            activo=_to_bool(row.get(col_activo), default=True) if col_activo else True,
            esDestacado=False,
            ordenCatalogo=1,
            imagenUrl=image_url,
            createdAt=datetime.now(timezone.utc),
        )

        if apply_changes:
            db.add(producto)
            db.flush()

            # No se modifica modelo/esquema; si columna stock existe en BD, se actualiza por SQL.
            if has_stock_column and stock_value is not None:
                db.execute(
                    text("UPDATE Producto SET stock = :stock WHERE idProducto = :id_producto"),
                    {"stock": stock_value, "id_producto": next_id},
                )

        existing_names[normalized_name] = producto
        summary.productos_insertados += 1


def _onboard_clientes(
    db: Session,
    empresa_id: int,
    clientes_df: pd.DataFrame,
    summary: OnboardingSummary,
    apply_changes: bool,
    id_counters: dict[str, int],
) -> None:
    NIT_FLORA = "900993719-1"
    NIT_FLORA_NORMALIZADO = _normalizar_identificacion(NIT_FLORA)
    ALLOWED_TIPO_IDENT = {"CEDULA", "NIT"}

    col_ident = _find_column(clientes_df, "Identificacion", aliases=["Identificación"])
    col_tipo = _find_column(clientes_df, "Tipo", aliases=["tipoIdent", "TipoIdentificacion"])
    col_telefono = _find_column(clientes_df, "Telefono", aliases=["Celular", "Movil"])
    col_email = _find_column(clientes_df, "Email", aliases=["Correo", "CorreoElectronico"])

    col_primer_nombre = _find_column(
        clientes_df,
        "PrimerNombre",
        aliases=["Nombre", "Primer Nombre"],
    )
    col_primer_apellido = _find_column(
        clientes_df,
        "PrimerApellido",
        aliases=["Primer Apellido", "Apellido"],
    )

    clientes_existentes = db.query(Cliente).filter(Cliente.empresaID == empresa_id).all()
    by_ident = {
        _limpiar_identificacion(cliente.identificacion): cliente
        for cliente in clientes_existentes
        if cliente.identificacion is not None and _limpiar_identificacion(cliente.identificacion) != ""
    }

    for _, row in clientes_df.iterrows():
        ident = row.get(col_ident)
        ident_str = _limpiar_identificacion(ident)
        if not ident_str:
            summary.filas_cliente_sin_identificacion += 1
            summary.clientes_omitidos += 1
            continue

        if _normalizar_identificacion(ident_str) == NIT_FLORA_NORMALIZADO:
            summary.clientes_ignorados_nit_flora += 1
            summary.clientes_omitidos += 1
            continue

        if ident_str in by_ident:
            summary.clientes_ignorados_duplicado += 1
            summary.clientes_omitidos += 1
            continue

        telefono = row.get(col_telefono)
        email = row.get(col_email)

        tipo_value = row.get(col_tipo)
        tipo_ident = "CEDULA" if pd.isna(tipo_value) else str(tipo_value).strip().upper()
        if not tipo_ident or _normalize_text(tipo_ident) == "nan" or tipo_ident not in ALLOWED_TIPO_IDENT:
            tipo_ident = "CEDULA"

        primer_nombre_raw = row.get(col_primer_nombre)
        primer_apellido_raw = row.get(col_primer_apellido)
        primer_nombre = "" if pd.isna(primer_nombre_raw) else str(primer_nombre_raw).strip()
        primer_apellido = "" if pd.isna(primer_apellido_raw) else str(primer_apellido_raw).strip()
        nombre = " ".join(part for part in [primer_nombre, primer_apellido] if part).strip()
        if not nombre:
            nombre = "CLIENTE SIN NOMBRE"

        telefono_normalizado = normalizar_telefono(telefono)
        if not telefono_normalizado:
            summary.clientes_telefono_invalido += 1
            summary.clientes_omitidos += 1
            continue

        next_id = id_counters["cliente"]
        id_counters["cliente"] += 1
        cliente = Cliente(
            idCliente=next_id,
            empresaID=empresa_id,
            tipoIdent=tipo_ident,
            identificacion=ident_str,
            indicativo="+57",
            telefonoCompleto=telefono_normalizado,
            nombreCompleto=nombre,
            telefono=telefono_normalizado,
            email=(None if pd.isna(email) else str(email).strip()),
            activo=True,
            createdAt=datetime.now(timezone.utc),
        )

        if apply_changes:
            db.add(cliente)

        by_ident[ident_str] = cliente
        summary.clientes_creados += 1


def onboarding_empresa_excel(
    empresa_id: int,
    excel_path: Path,
    apply_changes: bool,
    empresa_nombre: str | None = None,
    empresa_nit: str | None = None,
    empresa_nombre_comercial: str | None = None,
) -> OnboardingSummary:
    if not excel_path.exists():
        raise FileNotFoundError(f"No existe el archivo Excel: {excel_path}")

    excel = pd.ExcelFile(excel_path)
    resolved = _resolve_required_sheets(excel)

    clientes_df = pd.read_excel(excel_path, sheet_name=resolved["CLIENTES"])
    catalogo_df = pd.read_excel(excel_path, sheet_name=resolved["CATALOGO"])

    summary = OnboardingSummary()
    db = SessionLocal()
    try:
        id_counters = _build_id_counters(db)
        _ensure_empresa(
            db,
            empresa_id,
            summary,
            apply_changes,
            empresa_nombre,
            empresa_nit,
            empresa_nombre_comercial,
        )
        _onboard_catalogo(db, empresa_id, catalogo_df, summary, apply_changes, id_counters)
        _onboard_clientes(db, empresa_id, clientes_df, summary, apply_changes, id_counters)

        if apply_changes:
            db.commit()
        else:
            db.rollback()

        return summary
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _resolve_empresa_id(empresa_id_arg: int | None) -> int:
    """Si no se recibe empresa_id, usa el siguiente idEmpresa disponible en BD."""
    if empresa_id_arg is not None:
        return empresa_id_arg

    db = SessionLocal()
    try:
        return _next_bigint_id(db, Empresa, Empresa.idEmpresa)
    finally:
        db.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Onboarding inicial de empresa desde Excel")
    parser.add_argument(
        "--empresa-id",
        type=int,
        required=False,
        help="ID de la empresa destino. Si no se envia, se usa el siguiente idEmpresa disponible.",
    )
    parser.add_argument(
        "--excel",
        type=Path,
        default=DEFAULT_EXCEL_PATH,
        help=f"Ruta del Excel de origen (default: {DEFAULT_EXCEL_PATH})",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Aplica cambios en base de datos. Si no se envia, corre en modo dry-run.",
    )
    parser.add_argument(
        "--empresa-nombre",
        type=str,
        required=False,
        help="Nombre de empresa a crear si no existe el idEmpresa.",
    )
    parser.add_argument(
        "--empresa-nit",
        type=str,
        required=False,
        help="NIT de empresa a crear si no existe el idEmpresa.",
    )
    parser.add_argument(
        "--empresa-nombre-comercial",
        type=str,
        required=False,
        help="Nombre comercial de empresa (crea o actualiza si el idEmpresa ya existe).",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    empresa_id = _resolve_empresa_id(args.empresa_id)

    summary = onboarding_empresa_excel(
        empresa_id=empresa_id,
        excel_path=args.excel,
        apply_changes=args.apply,
        empresa_nombre=args.empresa_nombre,
        empresa_nit=args.empresa_nit,
        empresa_nombre_comercial=args.empresa_nombre_comercial,
    )

    print("\n=== ONBOARDING EMPRESA EXCEL ===")
    print(f"Empresa ID destino: {empresa_id}")
    print(f"Empresa creada: {summary.empresa_creada}")
    print(f"Categorias creadas: {summary.categorias_creadas}")
    print(f"productos_insertados: {summary.productos_insertados}")
    print(f"productos_omitidos_por_duplicado: {summary.productos_omitidos_por_duplicado}")
    print(f"productos_sin_imagen: {summary.productos_sin_imagen}")
    print(f"Clientes insertados: {summary.clientes_creados}")
    print(f"Clientes ignorados por duplicado: {summary.clientes_ignorados_duplicado}")
    print(f"Clientes ignorados por ser NIT de Flora: {summary.clientes_ignorados_nit_flora}")
    print(f"Clientes con telefono invalido: {summary.clientes_telefono_invalido}")
    print(f"Clientes omitidos (total): {summary.clientes_omitidos}")
    print(f"Filas cliente sin identificacion: {summary.filas_cliente_sin_identificacion}")

    if args.apply:
        print("Modo: APPLY (cambios guardados)")
    else:
        print("Modo: DRY-RUN (sin cambios en BD)")


if __name__ == "__main__":
    main()
