# --- EJECUCIÓN DIRECTA DE LIMPIEZA DE CATEGORÍAS ---
import argparse
from app.database import SessionLocal
from dataclasses import dataclass, field
from sqlalchemy.orm import Session
from dataclasses import dataclass, field

@dataclass
class Stats:
    clientes_insertados: int = 0
    clientes_duplicados: int = 0
    barrios_insertados: int = 0
    barrios_duplicados: int = 0
    categorias_insertadas: int = 0
    productos_insertados: int = 0
    productos_duplicados: int = 0
    pedidos_insertados: int = 0
    pedidos_duplicados: int = 0
    detalles_insertados: int = 0
    domiciliarios_insertados: int = 0
    domiciliarios_duplicados: int = 0
    entregas_insertadas: int = 0
    insumos_insertados: int = 0
    inventario_insertado: int = 0
    movimientos_inventario_insertados: int = 0
    floristas_insertados: int = 0
    floristas_duplicados: int = 0
    pagos_insertados: int = 0
    errores: int = 0
    warnings: list[str] = field(default_factory=list)


    from app.models.producto import Producto
    """
    Limpia duplicados, normaliza nombres, globaliza categorias (empresaID=NULL),
    asegura unicidad y actualiza FK en Producto y PedidoDetalle.
    """
    from app.models.categoria import Categoria
    from app.models.producto import Producto
    from app.models.pedidodetalle import PedidoDetalle
    from sqlalchemy import and_

    # 1. Normalizar nombres y limpiar espacios
    categorias = db.query(Categoria).all()
    nombre_map = {}
    for cat in categorias:
        nombre_norm = normalize_text(cat.nombreCategoria)
        cat.nombreCategoria = nombre_norm
        cat.empresaID = None  # Globalizar
        db.flush()
        if nombre_norm in nombre_map:
            # Duplicado: migrar FK y eliminar
            cat_id_keep = nombre_map[nombre_norm]
            # Actualizar FK en Producto
            db.query(Producto).filter(Producto.categoriaID == cat.idCategoria).update({Producto.categoriaID: cat_id_keep})
            # Actualizar FK en PedidoDetalle
            db.query(PedidoDetalle).filter(PedidoDetalle.categoriaID == cat.idCategoria).update({PedidoDetalle.categoriaID: cat_id_keep})
            db.delete(cat)
            stats.categorias_insertadas -= 1
        else:
            nombre_map[nombre_norm] = cat.idCategoria
    db.flush()

    # 2. Reportar categorías finales
    print(f"Categorías globales: {len(nombre_map)}")
    for nombre, idcat in nombre_map.items():
        print(f"  - {nombre} (id={idcat})")
    from app.models.pedidodetalle import PedidoDetalle
    from sqlalchemy import and_

    # 1. Normalizar nombres y limpiar espacios

    # Definición de Stats antes del main
    categorias = db.query(Categoria).all()
    nombre_map = {}
    for cat in categorias:
        nombre_norm = normalize_text(cat.nombreCategoria)
        cat.nombreCategoria = nombre_norm
        cat.empresaID = None  # Globalizar
        db.flush()
        if nombre_norm in nombre_map:
            # Duplicado: migrar FK y eliminar
            cat_id_keep = nombre_map[nombre_norm]
            # Actualizar FK en Producto
            db.query(Producto).filter(Producto.categoriaID == cat.idCategoria).update({Producto.categoriaID: cat_id_keep})
            # Actualizar FK en PedidoDetalle
            db.query(PedidoDetalle).filter(PedidoDetalle.categoriaID == cat.idCategoria).update({PedidoDetalle.categoriaID: cat_id_keep})
            db.delete(cat)
            stats.categorias_insertadas -= 1
        else:
            nombre_map[nombre_norm] = cat.idCategoria
    db.flush()

    # 2. Reportar categorías finales
    print(f"Categorías globales: {len(nombre_map)}")
    for nombre, idcat in nombre_map.items():
        print(f"  - {nombre} (id={idcat})")
from app.models.empleado import Empleado
from app.models.entrega import Entrega
from app.models.estadopedido import EstadoPedido
from app.models.florista import Florista
from app.models.insumo import Insumo
from app.models.inventario import Inventario
from app.models.movimientoinventario import MovimientoInventario
from app.models.pago import Pago
from app.models.pedido import Pedido
from app.models.pedidodetalle import PedidoDetalle
from app.models.producto import Producto

DEFAULT_EXCEL = Path("csv/empresas/flora/FLORA_APP_V2.xlsx")


@dataclass
class Stats:
    clientes_insertados: int = 0
    clientes_duplicados: int = 0
    barrios_insertados: int = 0
    barrios_duplicados: int = 0
    categorias_insertadas: int = 0
    productos_insertados: int = 0
    productos_duplicados: int = 0
    pedidos_insertados: int = 0
    pedidos_duplicados: int = 0
    detalles_insertados: int = 0
    domiciliarios_insertados: int = 0
    domiciliarios_duplicados: int = 0
    entregas_insertadas: int = 0
    def limpiar_y_globalizar_categorias(db: Session, stats: 'Stats') -> None:
        """
        Limpia duplicados, normaliza nombres, globaliza categorias (empresaID=NULL),
        asegura unicidad y actualiza FK en Producto y PedidoDetalle.
        """
        from app.models.categoria import Categoria
        from app.models.producto import Producto
        from app.models.pedidodetalle import PedidoDetalle
        from sqlalchemy import and_

        # 1. Normalizar nombres y limpiar espacios
        categorias = db.query(Categoria).all()
        nombre_map = {}
        for cat in categorias:
            nombre_norm = normalize_text(cat.nombreCategoria)
            cat.nombreCategoria = nombre_norm
            cat.empresaID = None  # Globalizar
            db.flush()
            if nombre_norm in nombre_map:
                # Duplicado: migrar FK y eliminar
                cat_id_keep = nombre_map[nombre_norm]
                # Actualizar FK en Producto
                db.query(Producto).filter(Producto.categoriaID == cat.idCategoria).update({Producto.categoriaID: cat_id_keep})
                # Actualizar FK en PedidoDetalle
                db.query(PedidoDetalle).filter(PedidoDetalle.categoriaID == cat.idCategoria).update({PedidoDetalle.categoriaID: cat_id_keep})
                db.delete(cat)
                stats.categorias_insertadas -= 1
            else:
                nombre_map[nombre_norm] = cat.idCategoria
        db.flush()

        # 2. Reportar categorías finales
        print(f"Categorías globales: {len(nombre_map)}")
        for nombre, idcat in nombre_map.items():
            print(f"  - {nombre} (id={idcat})")
        return default


def parse_int(value: Any, default: int = 0) -> int:
    if value is None or pd.isna(value):
        return default
    text = str(value).strip()
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]
    text = re.sub(r"[^0-9-]", "", text)
    if text == "":
        return default
    try:
        return int(text)
    except ValueError:
        return default


def parse_datetime(value: Any) -> datetime:
    if value is None or pd.isna(value):
        return datetime.now()
    try:
        ts = pd.to_datetime(value)
        if pd.notna(ts):
            return ts.to_pydatetime()
    except Exception:
        pass
    return datetime.now()


def parse_phone(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    digits = re.sub(r"\D", "", str(value))
    if digits.startswith("57"):
        digits = digits[2:]
    if len(digits) >= 10:
        digits = digits[-10:]
    return digits


def find_sheet(xls: pd.ExcelFile, *aliases: str) -> str | None:
    alias_keys = {normalize_key(a) for a in aliases}
    for name in xls.sheet_names:
        if normalize_key(name) in alias_keys:
            return name
    return None


def find_column(df: pd.DataFrame, expected: str, aliases: list[str] | None = None) -> str:
    aliases = aliases or []
    keys = {normalize_key(expected), *[normalize_key(a) for a in aliases]}
    for col in df.columns:
        if normalize_key(col) in keys:
            return col
    raise ValueError(f"No se encontro columna '{expected}'. Columnas: {list(df.columns)}")


def find_column_optional(df: pd.DataFrame, expected: str, aliases: list[str] | None = None) -> str | None:
    try:
        return find_column(df, expected, aliases)
    except ValueError:
        return None


def get_or_create_categoria(db: Session, empresa_id: int, nombre: str, stats: Stats) -> Categoria:
    nombre = normalize_text(nombre) or "general"
    categoria = (
        db.query(Categoria)
        .filter(Categoria.empresaID == empresa_id, func.lower(Categoria.nombreCategoria) == nombre)
        .first()
    )
    if categoria:
        return categoria

    next_id = int(db.query(func.max(Categoria.idCategoria)).scalar() or 0) + 1
    categoria = Categoria(
        idCategoria=next_id,
        empresaID=empresa_id,
        nombreCategoria=nombre,
        descripcion="",
        orden=1,
        activo=True,
        createdAt=datetime.now(),
        updatedAt=datetime.now(),
    )
    db.add(categoria)
    db.flush()
    stats.categorias_insertadas += 1
    return categoria


def migrar_clientes(db: Session, xls: pd.ExcelFile, empresa_id: int, stats: Stats) -> None:
    sheet = find_sheet(xls, "clientes")
    if not sheet:
        stats.warnings.append("No se encontro hoja Clientes")
        return

    df = pd.read_excel(xls, sheet_name=sheet)
    col_nombre = find_column(df, "PrimerNombre", ["Nombre", "nombre completo", "Cliente"])
    col_apellido = find_column_optional(df, "PrimerApellido", ["Apellido", "SegundoApellido"])
    col_ident = find_column_optional(df, "Identificacion", ["identificacion", "cedula", "documento"])


        if not ident:
            """
            Limpia duplicados, normaliza nombres, globaliza categorias (empresaID=NULL),
            asegura unicidad y actualiza FK en Producto y PedidoDetalle.
            """
            from app.models.categoria import Categoria
            from app.models.producto import Producto
            from app.models.pedidodetalle import PedidoDetalle
            from sqlalchemy import and_

            # 1. Normalizar nombres y limpiar espacios
            categorias = db.query(Categoria).all()
            nombre_map = {}
            for cat in categorias:
                nombre_norm = normalize_text(cat.nombreCategoria)
                cat.nombreCategoria = nombre_norm
                cat.empresaID = None  # Globalizar
                db.flush()
                if nombre_norm in nombre_map:
                    # Duplicado: migrar FK y eliminar
                    cat_id_keep = nombre_map[nombre_norm]
                    # Actualizar FK en Producto
                    db.query(Producto).filter(Producto.categoriaID == cat.idCategoria).update({Producto.categoriaID: cat_id_keep})
                    # Actualizar FK en PedidoDetalle
                    db.query(PedidoDetalle).filter(PedidoDetalle.categoriaID == cat.idCategoria).update({PedidoDetalle.categoriaID: cat_id_keep})
                    db.delete(cat)
                    stats.categorias_insertadas -= 1
                else:
                    nombre_map[nombre_norm] = cat.idCategoria
            db.flush()

            # 2. Reportar categorías finales
            print(f"Categorías globales: {len(nombre_map)}")
            for nombre, idcat in nombre_map.items():
                print(f"  - {nombre} (id={idcat})")
            ident = f"tel-{telefono}"

        ident_norm = normalize_text(ident)
        if ident_norm in existing_by_ident:
            stats.clientes_duplicados += 1
            continue

        cliente = Cliente(
            idCliente=next_id,
            empresaID=empresa_id,
            tipoIdent="cedula",
            identificacion=ident,
            indicativo="57",
            telefonoCompleto=f"57{telefono}",
            nombreCompleto=nombre_completo,
            telefono=telefono,
            email=normalize_text(row.get(col_email)) if col_email else None,
            activo=True,
            createdAt=datetime.now(),
            updatedAt=datetime.now(),
        )
        db.add(cliente)
        existing_by_phone[telefono] = next_id
        existing_by_ident[ident_norm] = next_id
        next_id += 1
        stats.clientes_insertados += 1


def migrar_barrios(db: Session, xls: pd.ExcelFile, empresa_id: int, sucursal_id: int, stats: Stats) -> None:
    sheet = find_sheet(xls, "barrio", "barrios")
    if not sheet:
        stats.warnings.append("No se encontro hoja Barrio")
        return

    df = pd.read_excel(xls, sheet_name=sheet)
    col_nombre = find_column(df, "Nombre", ["Barrio", "Nombre Barrio"])
    col_costo = find_column_optional(df, "Valor Domicilio", ["Costo", "Costo Domicilio"])
    col_zona = find_column_optional(df, "Zona", ["zonaid"])

    existing = {
        normalize_text(b.nombreBarrio): b.idBarrio
        for b in db.query(Barrio).filter(Barrio.empresaID == empresa_id).all()
    }

    next_id = int(db.query(func.max(Barrio.idBarrio)).scalar() or 0) + 1

    for _, row in df.iterrows():
        nombre = normalize_text(row.get(col_nombre))
        if not nombre:
            continue

        if nombre in existing:
            stats.barrios_duplicados += 1
            continue

        zona = parse_int(row.get(col_zona), default=1) if col_zona else 1
        costo = parse_decimal(row.get(col_costo), Decimal("0")) if col_costo else Decimal("0")

        barrio = Barrio(
            idBarrio=next_id,
            empresaID=empresa_id,
            sucursalID=sucursal_id,
            zonaID=zona,
            nombreBarrio=nombre,
            costoDomicilio=costo,
            activo=True,
            createdAt=datetime.now(),
            updatedAt=datetime.now(),
        )
        db.add(barrio)
        existing[nombre] = next_id
        next_id += 1
        stats.barrios_insertados += 1


def migrar_catalogo(db: Session, xls: pd.ExcelFile, empresa_id: int, stats: Stats) -> None:
    sheets = [
        find_sheet(xls, "catalogo"),
        find_sheet(xls, "catalogo_arreglos"),
    ]
    sheets = [s for s in sheets if s]
    if not sheets:
        stats.warnings.append("No se encontraron hojas Catalogo/CATALOGO_ARREGLOS")
        return

    existing_products = {
        normalize_text(p.nombreProducto): p.idProducto
        for p in db.query(Producto).filter(Producto.empresaID == empresa_id).all()
    }

    next_id = int(db.query(func.max(Producto.idProducto)).scalar() or 0) + 1

    for sheet in sheets:
        df = pd.read_excel(xls, sheet_name=sheet)
        col_nombre = find_column_optional(
            df,
            "Producto",
            ["Nombre", "name", "producto_nombre", "nombre_producto", "COD", "CODIGO"],
        )
        if not col_nombre:
            stats.warnings.append(f"Hoja {sheet}: sin columna de nombre/codigo de producto")
            continue

        col_precio = find_column_optional(
            df,
            "Precio",
            ["price", "precioBase", " price", "BASE", "PVP Unidad", "PVP"],
        )
        col_categoria = find_column_optional(df, "Categoria", ["categoriaNombre", "tipo"])
        col_desc = find_column_optional(df, "Descripcion", ["detalle"])
        col_img = find_column_optional(df, "Image", ["imagen", "imagenUrl", "img"])
        col_activo = find_column_optional(df, "Activo", ["Disponible", "Estado", "activo"])

        for _, row in df.iterrows():
            nombre = normalize_text(row.get(col_nombre))
            if not nombre:
                continue

            if nombre in existing_products:
                stats.productos_duplicados += 1
                continue

            categoria_nombre = normalize_text(row.get(col_categoria)) if col_categoria else "general"
            if not categoria_nombre:
                categoria_nombre = "arreglos" if normalize_key(sheet) == "catalogoarreglos" else "general"
            categoria = get_or_create_categoria(db, empresa_id, categoria_nombre, stats)

            producto = Producto(
                idProducto=next_id,
                empresaID=empresa_id,
                codigoProducto=f"prd-{empresa_id}-{next_id}",
                categoriaID=categoria.idCategoria,
                nombreProducto=nombre,
                descripcion=normalize_text(row.get(col_desc)) if col_desc else "",
                precioBase=parse_decimal(row.get(col_precio), Decimal("0")) if col_precio else Decimal("0"),
                porcentajeIva=Decimal("0"),
                ivaIncluido=False,
                tiempoBaseProduccionMin=30,
                nivelComplejidad="media",
                activo=(str(row.get(col_activo)).strip().lower() not in {"0", "no", "false", "inactivo"}) if col_activo else True,
                esDestacado=False,
                ordenCatalogo=1,
                imagenUrl=normalize_text(row.get(col_img)) if col_img else None,
                createdAt=datetime.now(),
                updatedAt=datetime.now(),
            )
            db.add(producto)
            existing_products[nombre] = next_id
            next_id += 1
            stats.productos_insertados += 1


def migrar_pedidos(db: Session, xls: pd.ExcelFile, empresa_id: int, sucursal_id: int, stats: Stats) -> None:
    sheet = find_sheet(xls, "registros", "registro")
    if not sheet:
        stats.warnings.append("No se encontro hoja Registros")
        return

    df = pd.read_excel(xls, sheet_name=sheet)
    col_pedido = find_column(df, "Pedido", ["NoPedido", "NPedido", "N Pedido"])
    col_ident = find_column_optional(df, "Identificacion", ["documento", "cedula"])
    col_tel = find_column_optional(df, "Telefono", ["Celular", "Telefono Cliente"])
    col_fecha = find_column_optional(df, "Fecha", ["Fecha Pedido"])
    col_total = find_column_optional(df, "Total", ["total neto"])
    col_iva = find_column_optional(df, "Iva", ["iva"])

    estado = (
        db.query(EstadoPedido)
        .filter(func.lower(EstadoPedido.nombreEstado) == "creado")
        .first()
    )
    if not estado:
        estado = db.query(EstadoPedido).order_by(EstadoPedido.idEstadoPedido.asc()).first()
    if not estado:
        raise ValueError("No existe EstadoPedido en la base de datos")

    existing_pedidos = {
        p.numeroPedido: p.idPedido
        for p in db.query(Pedido).filter(Pedido.empresaID == empresa_id).all()
        if p.numeroPedido is not None
    }

    clientes_by_ident = {
        normalize_text(c.identificacion): c
        for c in db.query(Cliente).filter(Cliente.empresaID == empresa_id).all()
    }
    clientes_by_phone = {
        parse_phone(c.telefono): c
        for c in db.query(Cliente).filter(Cliente.empresaID == empresa_id).all()
    }

    next_id = int(db.query(func.max(Pedido.idPedido)).scalar() or 0) + 1

    for _, row in df.iterrows():
        numero_pedido = parse_int(row.get(col_pedido), default=0)
        if numero_pedido <= 0:
            continue

        if numero_pedido in existing_pedidos:
            stats.pedidos_duplicados += 1
            continue

        cliente = None
        if col_ident:
            ident = normalize_text(row.get(col_ident))
            if ident:
                cliente = clientes_by_ident.get(ident)
        if not cliente and col_tel:
            tel = parse_phone(row.get(col_tel))
            if tel:
                cliente = clientes_by_phone.get(tel)
        if not cliente:
            continue

        fecha = parse_datetime(row.get(col_fecha)) if col_fecha else datetime.now()
        total_neto = parse_decimal(row.get(col_total), Decimal("0")) if col_total else Decimal("0")
        total_iva = parse_decimal(row.get(col_iva), Decimal("0")) if col_iva else Decimal("0")
        total_bruto = total_neto - total_iva
        if total_bruto < 0:
            total_bruto = Decimal("0")

        pedido = Pedido(
            idPedido=next_id,
            empresaID=empresa_id,
            sucursalID=sucursal_id,
            clienteID=cliente.idCliente,
            fechaPedido=fecha,
            fechaPedidoDate=fecha.date(),
            horaPedido=fecha.time().replace(microsecond=0),
            estadoPedidoID=estado.idEstadoPedido,
            version=1,
            motivoRechazo=None,
            totalBruto=total_bruto,
            totalIva=total_iva,
            totalNeto=total_neto,
            numeroPedido=numero_pedido,
            codigoPedido=f"ped-{numero_pedido}",
            createdAt=datetime.now(),
            updatedAt=datetime.now(),
        )
        db.add(pedido)
        existing_pedidos[numero_pedido] = next_id
        next_id += 1
        stats.pedidos_insertados += 1


def migrar_detalle_pedidos(db: Session, xls: pd.ExcelFile, empresa_id: int, sucursal_id: int, stats: Stats) -> None:
    sheet = find_sheet(xls, "produccion")
    if not sheet:
        stats.warnings.append("No se encontro hoja Produccion")
        return

    df = pd.read_excel(xls, sheet_name=sheet)
    col_pedido = find_column(df, "N°Pedido", ["NoPedido", "Pedido", "NPedido"])
    col_producto = find_column(df, "Producto", ["arreglo", "nombre producto"])
    col_cantidad = find_column_optional(df, "Cantidad", ["cant"])
    col_precio = find_column_optional(df, "Precio", ["valor", "precio unitario"])

    pedidos_map = {
        p.numeroPedido: p
        for p in db.query(Pedido).filter(Pedido.empresaID == empresa_id).all()
        if p.numeroPedido is not None
    }
    productos_map = {
        normalize_text(p.nombreProducto): p
        for p in db.query(Producto).filter(Producto.empresaID == empresa_id).all()
    }

    existing_detail_keys = {
        (d.pedidoID, d.productoID)
        for d in db.query(PedidoDetalle).filter(PedidoDetalle.empresaID == empresa_id).all()
    }

    next_id = int(db.query(func.max(PedidoDetalle.idPedidoDetalle)).scalar() or 0) + 1

    for _, row in df.iterrows():
        numero_pedido = parse_int(row.get(col_pedido), default=0)
        if numero_pedido <= 0:
            continue

        pedido = pedidos_map.get(numero_pedido)
        if not pedido:
            continue

        producto_nombre = normalize_text(row.get(col_producto))
        if not producto_nombre:
            continue
        producto = productos_map.get(producto_nombre)
        if not producto:
            continue

        key = (pedido.idPedido, producto.idProducto)
        if key in existing_detail_keys:
            continue

        cantidad = parse_decimal(row.get(col_cantidad), Decimal("1")) if col_cantidad else Decimal("1")
        if cantidad <= 0:
            cantidad = Decimal("1")
        precio = parse_decimal(row.get(col_precio), Decimal("0")) if col_precio else Decimal("0")
        if precio <= 0:
            precio = parse_decimal(producto.precioBase, Decimal("0"))
        subtotal = cantidad * precio

        detalle = PedidoDetalle(
            idPedidoDetalle=next_id,
            empresaID=empresa_id,
            sucursalID=sucursal_id,
            pedidoID=pedido.idPedido,
            productoID=producto.idProducto,
            cantidad=cantidad,
            precioUnitario=precio,
            ivaUnitario=Decimal("0"),
            subtotal=subtotal,
        )
        db.add(detalle)
        existing_detail_keys.add(key)
        next_id += 1
        stats.detalles_insertados += 1


def migrar_domiciliarios(db: Session, xls: pd.ExcelFile, empresa_id: int, sucursal_id: int, stats: Stats) -> None:
    sheet = find_sheet(xls, "domiciliarios", "domiciliario")
    if not sheet:
        stats.warnings.append("No se encontro hoja Domiciliarios")
        return

    df = pd.read_excel(xls, sheet_name=sheet)
    col_nombre = find_column(df, "Nombre", ["Domiciliario", "Empleado"])
    col_tel = find_column_optional(df, "Telefono", ["Celular"])

    existing = {
        normalize_text(d.nombre): d.idDomiciliario
        for d in db.query(Domiciliario).filter(Domiciliario.empresaID == empresa_id).all()
    }
    next_id = int(db.query(func.max(Domiciliario.idDomiciliario)).scalar() or 0) + 1

    for _, row in df.iterrows():
        nombre = normalize_text(row.get(col_nombre))
        if not nombre:
            continue
        if nombre in existing:
            stats.domiciliarios_duplicados += 1
            continue

        dom = Domiciliario(
            idDomiciliario=next_id,
            empresaID=empresa_id,
            sucursalID=sucursal_id,
            nombre=nombre,
            telefono=parse_phone(row.get(col_tel)) if col_tel else None,
            activo=True,
            createdAt=datetime.now(),
            updatedAt=datetime.now(),
        )
        db.add(dom)
        existing[nombre] = next_id
        next_id += 1
        stats.domiciliarios_insertados += 1


def migrar_entregas(db: Session, xls: pd.ExcelFile, empresa_id: int, sucursal_id: int, stats: Stats) -> None:
    sheet = find_sheet(xls, "domicilios")
    if not sheet:
        stats.warnings.append("No se encontro hoja Domicilios")
        return

    df = pd.read_excel(xls, sheet_name=sheet)
    col_pedido = find_column(df, "N°Pedido", ["NoPedido", "Pedido", "NPedido"])
    col_barrio = find_column_optional(df, "Barrio", ["Nombre Barrio"])
    col_direccion = find_column_optional(df, "Direccion", ["Direccion Cliente"])
    col_destinatario = find_column_optional(df, "Destinatario", ["Cliente"])
    col_tel = find_column_optional(df, "Telefono", ["Celular", "Telefono Destino"])
    col_fecha = find_column_optional(df, "Fecha Entrega", ["Fecha", "Entrega"])

    pedidos = {
        p.numeroPedido: p
        for p in db.query(Pedido).filter(Pedido.empresaID == empresa_id).all()
        if p.numeroPedido is not None
    }
    barrios = {
        normalize_text(b.nombreBarrio): b
        for b in db.query(Barrio).filter(Barrio.empresaID == empresa_id).all()
    }

    empleado_id = db.query(func.min(Empleado.idEmpleado)).filter(Empleado.empresaID == empresa_id).scalar()
    domiciliario_id = db.query(func.min(Domiciliario.idDomiciliario)).filter(Domiciliario.empresaID == empresa_id).scalar()

    existing_by_pedido = {
        e.pedidoID
        for e in db.query(Entrega).filter(Entrega.empresaID == empresa_id).all()
    }
    next_id = int(db.query(func.max(Entrega.idEntrega)).scalar() or 0) + 1

    for _, row in df.iterrows():
        numero_pedido = parse_int(row.get(col_pedido), default=0)
        if numero_pedido <= 0:
            continue

        pedido = pedidos.get(numero_pedido)
        if not pedido:
            continue
        if pedido.idPedido in existing_by_pedido:
            continue

        barrio_nombre = normalize_text(row.get(col_barrio)) if col_barrio else ""
        barrio = barrios.get(barrio_nombre)

        fecha_entrega = parse_datetime(row.get(col_fecha)) if col_fecha else None

        entrega = Entrega(
            idEntrega=next_id,
            empresaID=empresa_id,
            pedidoID=pedido.idPedido,
            empleadoID=empleado_id,
            estadoEntregaID=1,
            tipoEntrega="domicilio",
            destinatario=normalize_text(row.get(col_destinatario)) if col_destinatario else None,
            telefonoDestino=parse_phone(row.get(col_tel)) if col_tel else None,
            direccion=normalize_text(row.get(col_direccion)) if col_direccion else None,
            barrioID=barrio.idBarrio if barrio else None,
            barrioNombre=barrio_nombre or None,
            fechaEntrega=fecha_entrega,
            createdAt=datetime.now(),
            updatedAt=datetime.now(),
            sucursalID=sucursal_id,
            domiciliarioID=domiciliario_id,
            estado="pendiente",
            intentoNumero=1,
        )
        db.add(entrega)
        existing_by_pedido.add(pedido.idPedido)
        next_id += 1
        stats.entregas_insertadas += 1


def migrar_inventario(db: Session, xls: pd.ExcelFile, empresa_id: int, sucursal_id: int, stats: Stats) -> None:
    inv_sheet = find_sheet(xls, "inventario")
    mov_sheet = find_sheet(xls, "movimientos_inventario") or find_sheet(xls, "inventario_movimientos")

    insumo_cache = {
        normalize_text(i.nombreInsumo): i
        for i in db.query(Insumo).filter(Insumo.empresaID == empresa_id).all()
    }
    inventario_cache = {
        normalize_text(inv.nombre): inv
        for inv in db.query(Inventario).filter(Inventario.empresaID == empresa_id).all()
    }
    inventario_by_code = {
        normalize_text(inv.codigo): inv
        for inv in db.query(Inventario).filter(Inventario.empresaID == empresa_id).all()
        if inv.codigo
    }

    next_insumo = int(db.query(func.max(Insumo.idInsumo)).scalar() or 0) + 1
    next_inventario = int(db.query(func.max(Inventario.idInventario)).scalar() or 0) + 1
    next_mov = int(db.query(func.max(MovimientoInventario.idMovimiento)).scalar() or 0) + 1

    if inv_sheet:
        df = pd.read_excel(xls, sheet_name=inv_sheet)
        col_nombre = find_column(df, "Nombre", ["Producto", "Insumo", "item"])
        col_stock = find_column_optional(df, "Stock", ["Cantidad", "stock actual"])
        col_unidad = find_column_optional(df, "Unidad", ["unidad medida"])
        col_cat = find_column_optional(df, "Categoria", ["tipo"])
        col_color = find_column_optional(df, "Color")
        col_desc = find_column_optional(df, "Descripcion", ["detalle"])
        col_valor = find_column_optional(df, "Valor Unitario", ["costo", "valor"])

        for _, row in df.iterrows():
            nombre = normalize_text(row.get(col_nombre))
            if not nombre:
                continue

            insumo = insumo_cache.get(nombre)
            if not insumo:
                insumo = Insumo(
                    idInsumo=next_insumo,
                    empresaID=empresa_id,
                    codigoBarra=None,
                    nombreInsumo=nombre,
                    unidadMedida=normalize_text(row.get(col_unidad)) if col_unidad else "unidad",
                    stockMinimo=Decimal("0"),
                    activo=True,
                    createdAt=datetime.now(),
                    updatedAt=datetime.now(),
                )
                db.add(insumo)
                insumo_cache[nombre] = insumo
                next_insumo += 1
                stats.insumos_insertados += 1

            if nombre in inventario_cache:
                continue

            stock_actual = parse_decimal(row.get(col_stock), Decimal("0")) if col_stock else Decimal("0")
            inv = Inventario(
                idInventario=next_inventario,
                empresaID=empresa_id,
                insumoID=insumo.idInsumo,
                sucursalID=sucursal_id,
                stockActual=stock_actual,
                stockReservado=Decimal("0"),
                createdAt=datetime.now(),
                updatedAt=datetime.now(),
                codigo=f"inv-{empresa_id}-{next_inventario}",
                nombre=nombre,
                categoria=normalize_text(row.get(col_cat)) if col_cat else "general",
                subcategoria=None,
                color=normalize_text(row.get(col_color)) if col_color else None,
                descripcion=normalize_text(row.get(col_desc)) if col_desc else None,
                proveedorID=None,
                codigoProveedor=None,
                stockMinimo=Decimal("0"),
                valorUnitario=parse_decimal(row.get(col_valor), Decimal("0")) if col_valor else Decimal("0"),
                activo=True,
                fechaUltimaActualizacion=datetime.now(),
            )
            db.add(inv)
            inventario_cache[nombre] = inv
            inventario_by_code[normalize_text(inv.codigo)] = inv
            next_inventario += 1
            stats.inventario_insertado += 1
    else:
        stats.warnings.append("No se encontro hoja Inventario")

    if mov_sheet:
        dfm = pd.read_excel(xls, sheet_name=mov_sheet)
        col_codigo = find_column_optional(dfm, "CODIGO", ["Codigo", "COD", "codigo"])
        col_nombre = find_column_optional(dfm, "Nombre", ["Producto", "Insumo", "item"])
        col_tipo = find_column_optional(dfm, "Tipo Movimiento", ["tipo", "movimiento"])
        col_cantidad = find_column_optional(dfm, "Cantidad", ["valor", "stock"])
        col_fecha = find_column_optional(dfm, "Fecha")
        col_motivo = find_column_optional(dfm, "Motivo", ["observacion", "detalle"])

        for _, row in dfm.iterrows():
            inv = None
            if col_codigo:
                codigo = normalize_text(row.get(col_codigo))
                if codigo:
                    inv = inventario_by_code.get(codigo)

            if not inv and col_nombre:
                nombre = normalize_text(row.get(col_nombre))
                if nombre:
                    inv = inventario_cache.get(nombre)

            if not inv:
                continue

            tipo = normalize_text(row.get(col_tipo)) if col_tipo else "ajuste"
            if tipo not in {"entrada", "salida", "ajuste"}:
                tipo = "ajuste"

            mov = MovimientoInventario(
                idMovimiento=next_mov,
                empresaID=empresa_id,
                inventarioID=inv.idInventario,
                tipoMovimiento=tipo,
                cantidad=parse_decimal(row.get(col_cantidad), Decimal("0")) if col_cantidad else Decimal("0"),
                fecha=parse_datetime(row.get(col_fecha)) if col_fecha else datetime.now(),
                motivo=normalize_text(row.get(col_motivo)) if col_motivo else None,
                usuarioID=None,
                createdAt=datetime.now(),
            )
            db.add(mov)
            next_mov += 1
            stats.movimientos_inventario_insertados += 1
    else:
        stats.warnings.append("No se encontro hoja Movimientos_Inventario/Inventario_Movimientos")


def migrar_floristas(db: Session, xls: pd.ExcelFile, empresa_id: int, sucursal_id: int, stats: Stats) -> None:
    sheet = find_sheet(xls, "floristas", "florista")
    if not sheet:
        stats.warnings.append("No se encontro hoja Floristas")
        return

    df = pd.read_excel(xls, sheet_name=sheet)
    col_nombre = find_column(df, "Nombre", ["Florista", "Empleado"])
    col_capacidad = find_column_optional(df, "CargaHoy", ["Capacidad", "Cupo", "cargahoy"])
    col_estado = find_column_optional(df, "Disponibilidad", ["Estado", "Disponible"])

    existing = {
        normalize_text(f.nombre): f.idFlorista
        for f in db.query(Florista).filter(Florista.empresaID == empresa_id, Florista.sucursalID == sucursal_id).all()
    }

    next_id = int(db.query(func.max(Florista.idFlorista)).scalar() or 0) + 1

    for _, row in df.iterrows():
        nombre = normalize_text(row.get(col_nombre))
        if not nombre:
            continue
        if nombre in existing:
            stats.floristas_duplicados += 1
            continue

        estado = normalize_text(row.get(col_estado)) if col_estado else "activo"
        disponible = estado in {"activo", "disponible", "si", "1", "true"}

        florista = Florista(
            idFlorista=next_id,
            empresaID=empresa_id,
            sucursalID=sucursal_id,
            nombre=nombre,
            capacidadDiaria=max(parse_int(row.get(col_capacidad), 1), 1) if col_capacidad else 1,
            trabajosSimultaneosPermitidos=1,
            estado="activo" if disponible else "inactivo",
            activo=disponible,
            especialidades=None,
            createdAt=datetime.now(),
            updatedAt=datetime.now(),
        )
        db.add(florista)
        existing[nombre] = next_id
        next_id += 1
        stats.floristas_insertados += 1


def migrar_pagos(db: Session, xls: pd.ExcelFile, empresa_id: int, stats: Stats) -> None:
    sheet = find_sheet(xls, "pagos")
    if not sheet:
        stats.warnings.append("No se encontro hoja Pagos")
        return

    df = pd.read_excel(xls, sheet_name=sheet)
    col_pedido = find_column(df, "Pedido", ["PedidoID", "NPedido", "NoPedido", "N°Pedido", "N�Pedido"])
    col_monto = find_column_optional(df, "Monto", ["Valor", "Total", "total pagado"])
    col_estado = find_column_optional(df, "Estado")
    col_ref = find_column_optional(df, "Referencia", ["Transaccion", "tx"])
    col_metodo = find_column_optional(df, "Metodo", ["FormaPago", "medio"])
    col_fecha = find_column_optional(df, "Fecha", ["Fecha Pago"])

    pedidos = {
        p.numeroPedido: p
        for p in db.query(Pedido).filter(Pedido.empresaID == empresa_id).all()
        if p.numeroPedido is not None
    }
    existing_refs = {
        normalize_text(p.referencia)
        for p in db.query(Pago).filter(Pago.empresaID == empresa_id).all()
        if p.referencia
    }

    next_id = int(db.query(func.max(Pago.idPago)).scalar() or 0) + 1

    for _, row in df.iterrows():
        numero_pedido = parse_int(row.get(col_pedido), default=0)
        if numero_pedido <= 0:
            continue

        pedido = pedidos.get(numero_pedido)
        if not pedido:
            continue

        ref = normalize_text(row.get(col_ref)) if col_ref else ""
        if not ref:
            ref = f"pay-{pedido.idPedido}-{next_id}"
        if ref in existing_refs:
            continue

        pago = Pago(
            idPago=next_id,
            empresaID=empresa_id,
            pedidoID=pedido.idPedido,
            proveedor="wompi",
            referencia=ref,
            transaccionID=ref,
            estado=normalize_text(row.get(col_estado)) if col_estado else "pendiente",
            moneda="cop",
            monto=parse_decimal(row.get(col_monto), Decimal("0")) if col_monto else Decimal("0"),
            checkoutUrl=None,
            rawRespuesta=None,
            metodoPago=normalize_text(row.get(col_metodo)) if col_metodo else "desconocido",
            fechaPago=parse_datetime(row.get(col_fecha)) if col_fecha else datetime.now(),
            createdAt=datetime.now(),
            updatedAt=datetime.now(),
        )
        db.add(pago)
        existing_refs.add(ref)
        next_id += 1
        stats.pagos_insertados += 1


def run_migration(excel_path: Path, empresa_id: int, sucursal_id: int, dry_run: bool) -> Stats:
    if not excel_path.exists():
        raise FileNotFoundError(f"No existe el archivo Excel: {excel_path}")

    logging.info("Leyendo Excel: %s", excel_path)
    xls = pd.ExcelFile(excel_path)

    stats = Stats()
    db = SessionLocal()
    try:
        migrar_clientes(db, xls, empresa_id, stats)
        migrar_barrios(db, xls, empresa_id, sucursal_id, stats)
        migrar_catalogo(db, xls, empresa_id, stats)
        migrar_pedidos(db, xls, empresa_id, sucursal_id, stats)
        migrar_detalle_pedidos(db, xls, empresa_id, sucursal_id, stats)
        migrar_domiciliarios(db, xls, empresa_id, sucursal_id, stats)
        migrar_entregas(db, xls, empresa_id, sucursal_id, stats)
        migrar_inventario(db, xls, empresa_id, sucursal_id, stats)
        migrar_floristas(db, xls, empresa_id, sucursal_id, stats)
        migrar_pagos(db, xls, empresa_id, stats)

        if dry_run:
            db.rollback()
            logging.info("DRY RUN activo: cambios revertidos")
        else:
            db.commit()
            logging.info("Migracion aplicada correctamente")
    except Exception as exc:
        db.rollback()
        stats.errores += 1
        logging.exception("Error en migracion: %s", exc)
        raise
    finally:
        db.close()

    return stats


def print_summary(stats: Stats) -> None:
    print("\n=== RESUMEN MIGRACION FLORA ===")
    print(f"clientes_insertados: {stats.clientes_insertados}")
    print(f"clientes_duplicados: {stats.clientes_duplicados}")
    print(f"barrios_insertados: {stats.barrios_insertados}")
    print(f"barrios_duplicados: {stats.barrios_duplicados}")
    print(f"categorias_insertadas: {stats.categorias_insertadas}")
    print(f"productos_insertados: {stats.productos_insertados}")
    print(f"productos_duplicados: {stats.productos_duplicados}")
    print(f"pedidos_insertados: {stats.pedidos_insertados}")
    print(f"pedidos_duplicados: {stats.pedidos_duplicados}")
    print(f"detalles_insertados: {stats.detalles_insertados}")
    print(f"domiciliarios_insertados: {stats.domiciliarios_insertados}")
    print(f"domiciliarios_duplicados: {stats.domiciliarios_duplicados}")
    print(f"entregas_insertadas: {stats.entregas_insertadas}")
    print(f"insumos_insertados: {stats.insumos_insertados}")
    print(f"inventario_insertado: {stats.inventario_insertado}")
    print(f"movimientos_inventario_insertados: {stats.movimientos_inventario_insertados}")
    print(f"floristas_insertados: {stats.floristas_insertados}")
    print(f"floristas_duplicados: {stats.floristas_duplicados}")
    print(f"pagos_insertados: {stats.pagos_insertados}")
    print(f"errores: {stats.errores}")

    if stats.warnings:
        print("\nWarnings:")
        for w in stats.warnings:
            print(f"- {w}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Migrar FLORA_APP_V2.xlsx a base relacional")
    parser.add_argument("--excel", type=Path, default=DEFAULT_EXCEL, help="Ruta del Excel")
    parser.add_argument("--empresa-id", type=int, default=3, help="Empresa destino")
    parser.add_argument("--sucursal-id", type=int, default=1, help="Sucursal destino")
    parser.add_argument("--dry-run", action="store_true", help="Ejecuta sin persistir cambios")
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = build_parser().parse_args()

    stats = run_migration(
        excel_path=args.excel,
        empresa_id=args.empresa_id,
        sucursal_id=args.sucursal_id,
        dry_run=args.dry_run,
    )
    print_summary(stats)


if __name__ == "__main__":
    main()
