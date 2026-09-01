import re
import secrets
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from sqlalchemy import String, func, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.security import assert_same_empresa, get_current_auth_context, require_module_access
from app.database import get_db
from app.models.inventario import Inventario
from app.models.insumo import Insumo
from app.models.movimientoinventario import MovimientoInventario
from app.models.proveedor import Proveedor
from app.models.receta import Receta, RecetaDetalle
from app.services.cache import invalidate_cache_prefix
from app.schemas.inventario import (
    InventarioActivoRequest,
    InventarioCategoriaConfig,
    InventarioCategoriasResponse,
    InventarioCompraRequest,
    InventarioCreateRequest,
    InventarioDanoRequest,
    InventarioItem,
    InventarioListResponse,
    InventarioMetricasResponse,
    InventarioMutationResponse,
    InventarioStockAdjustRequest,
    InventarioUpdateRequest,
    MovimientoInventarioItem,
    MovimientoInventarioAnularRequest,
    MovimientoInventarioListResponse,
    MovimientoInventarioMetricasResponse,
    ProveedorCreateRequest,
    ProveedorItem,
    ProveedorListResponse,
    ProveedorUpdateRequest,
    RecetaCreateRequest,
    RecetaDetalleAgregarRequest,
    RecetaDetalleActualizarRequest,
    RecetaDetalleItem,
    RecetaItem,
    RecetaListItem,
    RecetaListResponse,
    RecetaUpdateRequest,
)

router = APIRouter(
    prefix="/inventario",
    tags=["Inventario"],
    dependencies=[Depends(require_module_access("inventario", "puedeVer"))],
)


def _has_column(db: Session, table_name: str, column_name: str) -> bool:
    result = db.execute(
        text(
            """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'petalops'
          AND table_name = :table_name
          AND column_name = :column_name
        LIMIT 1
        """
        ),
        {"table_name": str(table_name), "column_name": str(column_name)},
    ).first()
    return result is not None


def _status_stock(activo: bool, stock_actual: Decimal, stock_minimo: Decimal) -> str:
    if not bool(activo):
        return "Inactivo"
    if Decimal(stock_actual or 0) == Decimal("0"):
        return "Agotado"
    if Decimal(stock_actual or 0) <= Decimal(stock_minimo or 0):
        return "Bajo Stock"
    return "Disponible"


def _to_item(
    row: Inventario,
    *,
    codigo: str | None = None,
    nombre: str | None = None,
    categoria: str | None = None,
    subcategoria: str | None = None,
    color: str | None = None,
    descripcion: str | None = None,
    tamano: str | None = None,
    unidad_medida: str | None = None,
    fecha_vencimiento=None,
    marca: str | None = None,
    precio_venta: Decimal | None = None,
    proveedor_id: int | None = None,
    proveedor_nombre: str | None = None,
    codigo_proveedor: str | None = None,
) -> InventarioItem:
    stock_actual = Decimal(row.stockActual or 0)
    stock_minimo = Decimal(row.stockMinimo or 0)
    return InventarioItem(
        inventarioID=int(row.idInventario),
        empresaID=(int(row.empresaID) if row.empresaID is not None else 0),
        codigo=str(codigo or f"INS-{int(row.insumoID)}"),
        nombre=str(nombre or f"Insumo {int(row.insumoID)}"),
        categoria=str(categoria or "Insumos"),
        subcategoria=(str(subcategoria) if subcategoria is not None else None),
        color=(str(color) if color is not None else None),
        descripcion=(str(descripcion) if descripcion is not None else None),
        tamano=(str(tamano) if tamano is not None else None),
        unidadMedida=(str(unidad_medida) if unidad_medida is not None else None),
        fechaVencimiento=fecha_vencimiento,
        marca=(str(marca) if marca is not None else None),
        precioVenta=(Decimal(precio_venta) if precio_venta is not None else None),
        proveedorID=(int(proveedor_id) if proveedor_id is not None else None),
        proveedor=proveedor_nombre,
        codigoProveedor=(str(codigo_proveedor) if codigo_proveedor is not None else None),
        stockActual=stock_actual,
        stockMinimo=stock_minimo,
        valorUnitario=Decimal(row.valorUnitario or 0),
        activo=bool(row.activo),
        estadoStock=_status_stock(bool(row.activo), stock_actual, stock_minimo),
        fechaUltimaActualizacion=row.fechaUltimaActualizacion,
    )


def _normalize_movimiento_tipo(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("é", "e").replace("é", "e")
    mapping = {
        "entrada": "Entrada",
        "salida": "Salida",
        "ajuste": "Ajuste",
        "perdida": "Pérdida",
        "perdidas": "Pérdida",
    }
    # Also handle with accent
    normalized_acc = str(value or "").strip().lower()
    mapping_acc = {
        "pérdida": "Pérdida",
        "pérdidas": "Pérdida",
    }
    if normalized_acc in mapping_acc:
        return mapping_acc[normalized_acc]
    if normalized not in mapping:
        raise HTTPException(status_code=400, detail="tipoMovimiento debe ser Entrada, Salida, Ajuste o Pérdida")
    return mapping[normalized]


MOVIMIENTO_TIPO_CODIGO_A_ID = {
    "entrada": 1,
    "salida": 2,
    "ajuste": 3,
    "perdida": 4,
}

MOVIMIENTO_TIPO_ID_A_LABEL = {
    1: "Entrada",
    2: "Salida",
    3: "Ajuste",
    4: "Pérdida",
}


INVENTARIO_CATEGORIAS = {
    "FLORES": {
        "subcategorias": ["Rosas", "Follajes", "Tropicales", "Hortensias", "Lirios", "Orquideas", "Otro"],
        "unidades": ["Tallo", "Paquete", "Ramo", "Unidad"],
        "motivosSalida": ["Venta", "Produccion", "Muestra", "Consumo interno", "Regalo"],
        "motivosDano": [
            "Marchita",
            "Mal estado al recibir",
            "Daño por transporte",
            "Daño en produccion",
            "Plaga",
            "Regalo",
            "Otro",
        ],
        "motivosAjuste": ["Conteo fisico", "Error anterior", "Flor encontrada", "Flor extraviada"],
    },
    "BASES": {
        "subcategorias": ["Box", "Ceramica", "Vidrio", "Canasta", "Madera", "Otro"],
        "unidades": ["Unidad", "Caja", "Paquete"],
        "motivosSalida": ["Venta", "Produccion", "Daño"],
        "motivosDano": ["Rota", "Quebrada", "Golpe transporte", "Defecto de fabrica", "Otro"],
        "motivosAjuste": ["Conteo fisico", "Error anterior", "Base encontrada", "Base extraviada"],
    },
    "MATERIALES": {
        "subcategorias": [
            "Cintas",
            "Papeles",
            "Papel Coreano",
            "Celofan",
            "Moños",
            "Yute",
            "Oasis",
            "Plastico",
            "Frascos",
            "Tarjetas",
            "Sticker",
            "Herramientas",
        ],
        "unidades": ["Metro", "Rollo", "Unidad", "Paquete", "Caja", "Bolsa", "Frasco", "Kilogramo"],
        "motivosSalida": ["Produccion", "Venta", "Muestra", "Consumo interno", "Regalo"],
        "motivosDano": ["Mojado", "Roto", "Manchado", "Deteriorado", "Quebrado", "Dañado"],
        "motivosAjuste": ["Conteo fisico", "Error anterior", "Material encontrado", "Material extraviado"],
    },
    "ADICIONALES": {
        "subcategorias": ["Chocolates", "Peluche", "Vino", "Topper", "Otro"],
        "unidades": ["Unidad", "Caja", "Paquete", "Botella", "Bolsa", "Kit"],
        "motivosSalida": ["Venta", "Produccion", "Muestra", "Consumo interno", "Regalo"],
        "motivosDano": ["Vencimiento", "Chocolate vencido", "Botella rota", "Peluche manchado", "Otro"],
        "motivosAjuste": ["Conteo fisico", "Error anterior", "Producto encontrado", "Producto extraviado"],
    },
}


def _resolve_movimiento_tipo_id(db: Session, value: str) -> int:
    tipo = _normalize_movimiento_tipo(value)
    codigo_key = tipo.lower().replace("é", "e").replace("é", "e")
    row = db.execute(
        text(
            """
            SELECT id_tipo_movimiento
            FROM petalops.tipo_movimiento
            WHERE lower(translate(codigo, 'éíóú', 'eiou')) = lower(translate(:codigo, 'éíóú', 'eiou'))
               OR lower(translate(nombre, 'éíóú', 'eiou')) = lower(translate(:codigo, 'éíóú', 'eiou'))
            LIMIT 1
            """
        ),
        {"codigo": codigo_key},
    ).first()
    if row:
        return int(row[0])
    resolved = MOVIMIENTO_TIPO_CODIGO_A_ID.get(codigo_key)
    if resolved is None:
        raise HTTPException(status_code=400, detail="tipoMovimiento no configurado en catalogo")
    return int(resolved)


def _movimiento_tipo_label(value: int | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str) and value.strip() and not value.strip().isdigit():
        return _normalize_movimiento_tipo(value)
    try:
        return MOVIMIENTO_TIPO_ID_A_LABEL.get(int(value), str(value))
    except (TypeError, ValueError):
        return str(value)


def _get_proveedor_for_empresa(db: Session, empresa_id: int, proveedor_id: int) -> Proveedor | None:
    query = db.query(Proveedor).filter(Proveedor.idProveedor == int(proveedor_id))
    if _has_column(db, "proveedor", "empresa_id"):
        query = query.filter((Proveedor.empresaID == int(empresa_id)) | (Proveedor.empresaID.is_(None)))
    return query.first()


def _load_item_relations(db: Session, item: Inventario) -> tuple[Insumo | None, Proveedor | None]:
    insumo = (
        db.query(Insumo)
        .filter(
            Insumo.idInsumo == int(item.insumoID),
            Insumo.empresaID == int(item.empresaID),
        )
        .first()
    )
    proveedor = None
    if insumo and insumo.proveedorID is not None:
        proveedor = db.query(Proveedor).filter(Proveedor.idProveedor == int(insumo.proveedorID)).first()
    return insumo, proveedor


def _to_item_from_db(db: Session, item: Inventario) -> InventarioItem:
    insumo, proveedor = _load_item_relations(db, item)
    # Use new `categoria` column; fall back to `unidad_medida` for legacy records
    categoria_val = None
    if insumo:
        if insumo.categoria:
            categoria_val = str(insumo.categoria)
        elif insumo.unidadMedida:
            categoria_val = str(insumo.unidadMedida)
    return _to_item(
        item,
        codigo=(str(insumo.codigoBarra) if insumo and insumo.codigoBarra else None),
        nombre=(str(insumo.nombreInsumo) if insumo and insumo.nombreInsumo else None),
        categoria=categoria_val,
        subcategoria=(str(insumo.subcategoria) if insumo and insumo.subcategoria else None),
        color=(str(insumo.color) if insumo and insumo.color else None),
        descripcion=(str(insumo.descripcion) if insumo and insumo.descripcion else None),
        tamano=(str(insumo.tamano) if insumo and insumo.tamano else None),
        unidad_medida=(str(insumo.unidadMedida) if insumo and insumo.unidadMedida else None),
        fecha_vencimiento=(insumo.fechaVencimiento if insumo else None),
        marca=(str(insumo.marca) if insumo and insumo.marca else None),
        precio_venta=(Decimal(insumo.precioVenta) if insumo and insumo.precioVenta is not None else None),
        proveedor_id=(int(insumo.proveedorID) if insumo and insumo.proveedorID is not None else None),
        proveedor_nombre=(str(proveedor.nombreProveedor) if proveedor else None),
        codigo_proveedor=(str(proveedor.codigoProveedor) if proveedor and proveedor.codigoProveedor is not None else None),
    )


def _categoria_expr(has_categoria_col: bool):
    return Insumo.categoria if has_categoria_col else Insumo.unidadMedida


def _normalize_categoria(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped.upper() if stripped else None


def _movement_note(prefix: str, fields: dict[str, object | None]) -> str:
    extras = []
    for key, value in fields.items():
        if value is None or value == "":
            continue
        extras.append(f"{key}: {value}")
    detail = " | ".join(extras)
    note = f"{prefix} | {detail}" if detail else prefix
    return note[:250]


def _movement_tipo_key(value: int | str | None) -> str:
    label = _movimiento_tipo_label(value) if value is not None else ""
    normalized = (
        str(label or "")
        .strip()
        .lower()
        .replace("ÃƒÂ©", "e")
        .replace("Ã©", "e")
        .replace("é", "e")
    )
    if normalized in {"perdida", "perdidas", "dano", "danos", "daño"}:
        return "perdida"
    if normalized in {"entrada", "salida", "ajuste"}:
        return normalized
    return normalized


def _movement_estado(value: str | None) -> str:
    estado = str(value or "Registrado").strip()
    return estado or "Registrado"


def _movement_referencia(movimiento: MovimientoInventario) -> str:
    return str(getattr(movimiento, "referencia", None) or f"MOV-{int(movimiento.idMovimiento)}")


def _movimiento_item_response(
    mov: MovimientoInventario,
    inv: Inventario,
    ins: Insumo | None,
    *,
    has_categoria_col: bool,
) -> MovimientoInventarioItem:
    return MovimientoInventarioItem(
        movimientoID=int(mov.idMovimiento),
        inventarioID=int(mov.inventarioID),
        codigo=(str(ins.codigoBarra) if ins and ins.codigoBarra else f"INS-{int(inv.insumoID)}"),
        nombre=(str(ins.nombreInsumo) if ins and ins.nombreInsumo else f"Insumo {int(inv.insumoID)}"),
        categoria=(str(ins.categoria) if ins and has_categoria_col and ins.categoria else (str(ins.unidadMedida) if ins and ins.unidadMedida else None)),
        unidadMedida=(str(ins.unidadMedida) if ins and ins.unidadMedida else None),
        tipoMovimiento=_movimiento_tipo_label(mov.tipoMovimiento),
        cantidad=Decimal(mov.cantidad or 0),
        fecha=mov.fecha,
        motivo=(str(mov.motivo) if mov.motivo is not None else None),
        usuarioID=(int(mov.usuarioID) if mov.usuarioID is not None else None),
        estado=_movement_estado(getattr(mov, "estado", None)),
        referencia=_movement_referencia(mov),
        stockAnterior=(Decimal(mov.stockAnterior) if getattr(mov, "stockAnterior", None) is not None else None),
        stockNuevo=(Decimal(mov.stockNuevo) if getattr(mov, "stockNuevo", None) is not None else None),
        proveedorID=(int(mov.proveedorID) if getattr(mov, "proveedorID", None) is not None else None),
        numeroFactura=(str(mov.numeroFactura) if getattr(mov, "numeroFactura", None) is not None else None),
        responsable=(str(mov.responsable) if getattr(mov, "responsable", None) is not None else None),
        precioUnitario=(Decimal(mov.precioUnitario) if getattr(mov, "precioUnitario", None) is not None else None),
        fechaVencimiento=getattr(mov, "fechaVencimiento", None),
        evidenciaUrl=(str(mov.evidenciaUrl) if getattr(mov, "evidenciaUrl", None) is not None else None),
        pedidoReferencia=(str(mov.pedidoReferencia) if getattr(mov, "pedidoReferencia", None) is not None else None),
        observaciones=(str(mov.observaciones) if getattr(mov, "observaciones", None) is not None else None),
        anuladoAt=getattr(mov, "anuladoAt", None),
        anuladoPorUsuarioID=(int(mov.anuladoPorUsuarioID) if getattr(mov, "anuladoPorUsuarioID", None) is not None else None),
        motivoAnulacion=(str(mov.motivoAnulacion) if getattr(mov, "motivoAnulacion", None) is not None else None),
        movimientoOrigenID=(int(mov.movimientoOrigenID) if getattr(mov, "movimientoOrigenID", None) is not None else None),
    )


def _apply_stock_movement(
    *,
    db: Session,
    auth,
    item: Inventario,
    tipo_movimiento: str,
    cantidad: Decimal,
    motivo: str,
    fecha: datetime | None = None,
    stock_objetivo: Decimal | None = None,
    proveedor_id: int | None = None,
    numero_factura: str | None = None,
    responsable: str | None = None,
    unidad: str | None = None,
    precio_unitario: Decimal | None = None,
    fecha_vencimiento: date | None = None,
    evidencia_url: str | None = None,
    pedido_referencia: str | None = None,
    observaciones: str | None = None,
    referencia: str | None = None,
    movimiento_origen_id: int | None = None,
) -> Inventario:
    assert_same_empresa(auth, int(item.empresaID))

    movimiento_tipo = _normalize_movimiento_tipo(tipo_movimiento)
    movimiento_tipo_id = _resolve_movimiento_tipo_id(db, movimiento_tipo)
    cantidad = Decimal(cantidad or 0)
    now = datetime.now(timezone.utc)
    fecha_movimiento = fecha or now
    stock_actual = Decimal(item.stockActual or 0)
    tipo_key = _movement_tipo_key(movimiento_tipo)

    if tipo_key == "entrada":
        if cantidad <= 0:
            raise HTTPException(status_code=400, detail="cantidad debe ser mayor a 0 para Entrada")
        nuevo_stock = stock_actual + cantidad
        cantidad_mov = cantidad
    elif tipo_key in {'salida', 'perdida'}:
        if cantidad <= 0:
            raise HTTPException(status_code=400, detail=f"cantidad debe ser mayor a 0 para {movimiento_tipo}")
        nuevo_stock = stock_actual - cantidad
        if nuevo_stock < 0:
            raise HTTPException(status_code=400, detail="No se permite stock negativo")
        cantidad_mov = cantidad
    else:
        if stock_objetivo is None:
            raise HTTPException(status_code=400, detail="stockObjetivo es obligatorio para Ajuste")
        objetivo = Decimal(stock_objetivo)
        if objetivo < 0:
            raise HTTPException(status_code=400, detail="No se permite stock negativo")
        nuevo_stock = objetivo
        cantidad_mov = abs(nuevo_stock - stock_actual)

    item.stockActual = nuevo_stock
    item.fechaUltimaActualizacion = now
    item.updatedAt = now

    db.add(
        MovimientoInventario(
            empresaID=int(item.empresaID),
            inventarioID=int(item.idInventario),
            tipoMovimiento=movimiento_tipo_id,
            cantidad=cantidad_mov,
            fecha=fecha_movimiento,
            motivo=motivo.strip(),
            usuarioID=int(auth.userID),
            createdAt=now,
            estado="Registrado",
            stockAnterior=stock_actual,
            stockNuevo=nuevo_stock,
            referencia=referencia,
            proveedorID=(int(proveedor_id) if proveedor_id is not None else None),
            numeroFactura=numero_factura,
            responsable=responsable,
            unidad=unidad,
            precioUnitario=precio_unitario,
            fechaVencimiento=fecha_vencimiento,
            evidenciaUrl=evidencia_url,
            pedidoReferencia=pedido_referencia,
            observaciones=observaciones,
            movimientoOrigenID=movimiento_origen_id,
        )
    )
    return item


# ---------------------------------------------------------------------------
# Proveedores
# ---------------------------------------------------------------------------

@router.get("/proveedores", response_model=ProveedorListResponse)
def listar_proveedores(
    empresa_id: int = Query(..., alias="empresaID"),
    q: str | None = Query(None),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)

    has_empresa_scope = _has_column(db, "proveedor", "empresa_id")
    query = db.query(Proveedor)
    if has_empresa_scope:
        query = query.filter(Proveedor.empresaID == empresa_id)
    if q:
        term = f"%{q.strip()}%"
        query = query.filter(
            Proveedor.nombreProveedor.ilike(term)
            | Proveedor.codigoProveedor.ilike(term)
        )

    rows = query.order_by(Proveedor.nombreProveedor.asc()).all()
    items = [
        ProveedorItem(
            idProveedor=int(row.idProveedor),
            nombre=str(row.nombreProveedor or ""),
            codigoProveedor=(str(row.codigoProveedor) if row.codigoProveedor is not None else None),
            telefono=(str(row.telefono) if row.telefono is not None else None),
            email=(str(row.email) if row.email is not None else None),
            direccion=(str(row.direccion) if row.direccion is not None else None),
            activo=bool(row.activo),
        )
        for row in rows
    ]
    return ProveedorListResponse(items=items, total=len(items))


@router.post("/proveedores", response_model=ProveedorItem, dependencies=[Depends(require_module_access("inventario", "puedeCrear"))])
def crear_proveedor(
    payload: ProveedorCreateRequest,
    empresa_id: int = Query(..., alias="empresaID"),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)

    now = datetime.now(timezone.utc)
    empresa_scope = int(empresa_id) if _has_column(db, "proveedor", "empresa_id") else None
    try:
        row = db.execute(
            text(
                """
                INSERT INTO petalops.proveedor (
                    empresa_id,
                    nombre_proveedor,
                    codigo_proveedor,
                    telefono,
                    email,
                    direccion,
                    activo,
                    created_at,
                    updated_at
                )
                VALUES (
                    :empresa_id,
                    :nombre,
                    :codigo_proveedor,
                    :telefono,
                    :email,
                    :direccion,
                    :activo,
                    :created_at,
                    :updated_at
                )
                RETURNING id_proveedor
                """
            ),
            {
                "empresa_id": empresa_scope,
                "nombre": payload.nombre.strip(),
                "codigo_proveedor": (payload.codigoProveedor.strip() if payload.codigoProveedor else None),
                "telefono": (payload.telefono.strip() if payload.telefono else None),
                "email": (payload.email.strip() if payload.email else None),
                "direccion": (payload.direccion.strip() if payload.direccion else None),
                "activo": 1 if bool(payload.activo) else 0,
                "created_at": now,
                "updated_at": now,
            },
        ).first()
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=400, detail="No fue posible crear proveedor (codigo duplicado o datos invalidos)")

    proveedor = db.query(Proveedor).filter(Proveedor.idProveedor == int(row[0])).first()
    if not proveedor:
        raise HTTPException(status_code=500, detail="Proveedor creado pero no se pudo recargar")

    return ProveedorItem(
        idProveedor=int(proveedor.idProveedor),
        nombre=str(proveedor.nombreProveedor),
        codigoProveedor=(str(proveedor.codigoProveedor) if proveedor.codigoProveedor is not None else None),
        telefono=(str(proveedor.telefono) if proveedor.telefono is not None else None),
        email=(str(proveedor.email) if proveedor.email is not None else None),
        direccion=(str(proveedor.direccion) if proveedor.direccion is not None else None),
        activo=bool(proveedor.activo),
    )


@router.put("/proveedores/{proveedor_id}", response_model=ProveedorItem, dependencies=[Depends(require_module_access("inventario", "puedeEditar"))])
def actualizar_proveedor(
    proveedor_id: int,
    payload: ProveedorUpdateRequest,
    empresa_id: int = Query(..., alias="empresaID"),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)

    proveedor = _get_proveedor_for_empresa(db, empresa_id, proveedor_id)
    if not proveedor:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")

    proveedor.nombreProveedor = payload.nombre.strip()
    proveedor.codigoProveedor = (payload.codigoProveedor.strip() if payload.codigoProveedor else None)
    proveedor.telefono = (payload.telefono.strip() if payload.telefono else None)
    proveedor.email = (payload.email.strip() if payload.email else None)
    proveedor.direccion = (payload.direccion.strip() if payload.direccion else None)
    proveedor.activo = bool(payload.activo)
    proveedor.updatedAt = datetime.now(timezone.utc)

    try:
        db.commit()
        db.refresh(proveedor)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=400, detail="No fue posible actualizar proveedor (codigo duplicado o datos invalidos)")

    return ProveedorItem(
        idProveedor=int(proveedor.idProveedor),
        nombre=str(proveedor.nombreProveedor),
        codigoProveedor=(str(proveedor.codigoProveedor) if proveedor.codigoProveedor is not None else None),
        telefono=(str(proveedor.telefono) if proveedor.telefono is not None else None),
        email=(str(proveedor.email) if proveedor.email is not None else None),
        direccion=(str(proveedor.direccion) if proveedor.direccion is not None else None),
        activo=bool(proveedor.activo),
    )


# ---------------------------------------------------------------------------
# Inventario
# ---------------------------------------------------------------------------

@router.get("/categorias", response_model=InventarioCategoriasResponse)
def listar_categorias_inventario():
    items = [
        InventarioCategoriaConfig(
            categoria=categoria,
            subcategorias=list(config["subcategorias"]),
            unidades=list(config["unidades"]),
            motivosSalida=list(config["motivosSalida"]),
            motivosDano=list(config["motivosDano"]),
            motivosAjuste=list(config["motivosAjuste"]),
        )
        for categoria, config in INVENTARIO_CATEGORIAS.items()
    ]
    return InventarioCategoriasResponse(items=items)


@router.get("/metricas", response_model=InventarioMetricasResponse)
def obtener_metricas_inventario(
    empresa_id: int = Query(..., alias="empresaID"),
    categoria: str | None = Query(None),
    dias_vencimiento: int = Query(default=7, ge=1, le=365, alias="diasVencimiento"),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)

    has_categoria_col = _has_column(db, "insumo", "categoria")
    categoria_norm = _normalize_categoria(categoria)
    query = (
        db.query(Inventario, Insumo)
        .outerjoin(Insumo, Insumo.idInsumo == Inventario.insumoID)
        .filter(Inventario.empresaID == int(empresa_id))
    )
    if categoria_norm:
        query = query.filter(func.upper(_categoria_expr(has_categoria_col)) == categoria_norm)

    today = date.today()
    vence_hasta = today + timedelta(days=int(dias_vencimiento))
    total_referencias = 0
    disponibles = 0
    stock_bajo = 0
    agotados = 0
    inactivos = 0
    por_vencer = 0
    valor_inventario = Decimal("0")

    for item, insumo in query.all():
        total_referencias += 1
        stock_actual = Decimal(item.stockActual or 0)
        stock_minimo = Decimal(item.stockMinimo or 0)
        valor_inventario += stock_actual * Decimal(item.valorUnitario or 0)
        estado = _status_stock(bool(item.activo), stock_actual, stock_minimo)

        if estado == "Disponible":
            disponibles += 1
        elif estado == "Bajo Stock":
            stock_bajo += 1
        elif estado == "Agotado":
            agotados += 1
        elif estado == "Inactivo":
            inactivos += 1

        fecha_vencimiento = insumo.fechaVencimiento if insumo and has_categoria_col else None
        if fecha_vencimiento and today <= fecha_vencimiento <= vence_hasta:
            por_vencer += 1

    return InventarioMetricasResponse(
        empresaID=int(empresa_id),
        categoria=categoria_norm,
        totalReferencias=total_referencias,
        disponibles=disponibles,
        stockBajo=stock_bajo,
        agotados=agotados,
        inactivos=inactivos,
        porVencer=por_vencer,
        diasVencimiento=int(dias_vencimiento),
        valorInventario=valor_inventario,
    )


@router.get("", response_model=InventarioListResponse)
def listar_inventario(
    empresa_id: int = Query(..., alias="empresaID"),
    categoria: str | None = Query(None),
    subcategoria: str | None = Query(None),
    estado: str | None = Query(None),
    proveedor_id: int | None = Query(None, alias="proveedorID"),
    q: str | None = Query(None),
    solo_criticos: bool = Query(False, alias="soloCriticos"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=500, ge=1, le=1000, alias="pageSize"),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)

    query = (
        db.query(Inventario, Insumo, Proveedor)
        .outerjoin(Insumo, Insumo.idInsumo == Inventario.insumoID)
        .outerjoin(Proveedor, Proveedor.idProveedor == Insumo.proveedorID)
        .filter(Inventario.empresaID == empresa_id)
    )

    has_categoria_col = _has_column(db, "insumo", "categoria")

    if categoria:
        if has_categoria_col:
            # Filter by new categoria column; also match legacy unidad_medida for existing records
            query = query.filter(
                func.upper(Insumo.categoria) == categoria.strip().upper()
            )
        else:
            query = query.filter(func.upper(Insumo.unidadMedida) == categoria.strip().upper())

    if subcategoria and has_categoria_col and _has_column(db, "insumo", "subcategoria"):
        query = query.filter(func.upper(Insumo.subcategoria) == subcategoria.strip().upper())

    if proveedor_id is not None:
        query = query.filter(Proveedor.idProveedor == int(proveedor_id))

    if q:
        term = f"%{q.strip()}%"
        q_filter = (
            func.cast(Inventario.idInventario, String).ilike(term)
            | func.cast(Inventario.insumoID, String).ilike(term)
            | Insumo.nombreInsumo.ilike(term)
            | Insumo.codigoBarra.ilike(term)
            | Insumo.unidadMedida.ilike(term)
            | Proveedor.codigoProveedor.ilike(term)
            | Proveedor.nombreProveedor.ilike(term)
        )
        if has_categoria_col:
            q_filter = q_filter | Insumo.categoria.ilike(term)
        query = query.filter(q_filter)

    rows = query.order_by(Insumo.categoria.asc(), Insumo.nombreInsumo.asc()).all()

    items = []
    for item, insumo, proveedor in rows:
        # Resolve category: prefer new `categoria` column, fallback to `unidad_medida`
        categoria_val = None
        if insumo:
            if has_categoria_col and insumo.categoria:
                categoria_val = str(insumo.categoria)
            elif insumo.unidadMedida:
                categoria_val = str(insumo.unidadMedida)

        items.append(
            _to_item(
                item,
                codigo=(str(insumo.codigoBarra) if insumo and insumo.codigoBarra else None),
                nombre=(str(insumo.nombreInsumo) if insumo and insumo.nombreInsumo else None),
                categoria=categoria_val,
                subcategoria=(str(insumo.subcategoria) if insumo and has_categoria_col and insumo.subcategoria else None),
                color=(str(insumo.color) if insumo and has_categoria_col and insumo.color else None),
                descripcion=(str(insumo.descripcion) if insumo and has_categoria_col and insumo.descripcion else None),
                tamano=(str(insumo.tamano) if insumo and has_categoria_col and insumo.tamano else None),
                unidad_medida=(str(insumo.unidadMedida) if insumo and insumo.unidadMedida else None),
                fecha_vencimiento=(insumo.fechaVencimiento if insumo and has_categoria_col else None),
                marca=(str(insumo.marca) if insumo and has_categoria_col and insumo.marca else None),
                precio_venta=(Decimal(insumo.precioVenta) if insumo and has_categoria_col and insumo.precioVenta is not None else None),
                proveedor_id=(int(proveedor.idProveedor) if proveedor else None),
                proveedor_nombre=(str(proveedor.nombreProveedor) if proveedor else None),
                codigo_proveedor=(str(proveedor.codigoProveedor) if proveedor and proveedor.codigoProveedor is not None else None),
            )
        )

    if solo_criticos:
        items = [item for item in items if item.estadoStock in {"Bajo Stock", "Agotado"}]

    if estado:
        estado_norm = str(estado).strip().lower()
        items = [item for item in items if item.estadoStock.lower() == estado_norm]

    total = len(items)
    start = (page - 1) * page_size
    items_paginados = items[start:start + page_size]

    return InventarioListResponse(items=items_paginados, total=total, page=page, pageSize=page_size)


@router.post("", response_model=InventarioMutationResponse, dependencies=[Depends(require_module_access("inventario", "puedeCrear"))])
def crear_item_inventario(
    payload: InventarioCreateRequest,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, payload.empresaID)

    if payload.stockActual < 0:
        raise HTTPException(status_code=400, detail="stockActual no puede ser negativo")

    if payload.proveedorID is not None:
        proveedor = _get_proveedor_for_empresa(db, int(payload.empresaID), int(payload.proveedorID))
        if not proveedor:
            raise HTTPException(status_code=400, detail="Proveedor no valido para la empresa")

    if auth.sucursalID is None:
        raise HTTPException(status_code=400, detail="El usuario autenticado no tiene sucursal asignada")

    has_cat    = _has_column(db, "insumo", "categoria")
    has_marca  = has_cat and _has_column(db, "insumo", "marca")
    now = datetime.now(timezone.utc)

    try:
        if has_cat and has_marca:
            # Todas las migraciones aplicadas: guarda todos los campos
            insumo_row = db.execute(
                text(
                    """
                    INSERT INTO petalops.insumo (
                        empresa_id, codigo_barra, nombre_insumo, unidad_medida,
                        categoria, subcategoria, color, descripcion, tamano,
                        fecha_vencimiento, marca, precio_venta,
                        activo, created_at, updated_at, proveedor_id
                    ) VALUES (
                        :empresa_id, :codigo_barra, :nombre_insumo, :unidad_medida,
                        :categoria, :subcategoria, :color, :descripcion, :tamano,
                        :fecha_vencimiento, :marca, :precio_venta,
                        :activo, :created_at, :updated_at, :proveedor_id
                    )
                    RETURNING id_insumo
                    """
                ),
                {
                    "empresa_id": int(payload.empresaID),
                    "codigo_barra": payload.codigo.strip(),
                    "nombre_insumo": payload.nombre.strip(),
                    "unidad_medida": (payload.unidadMedida.strip() if payload.unidadMedida else "Unidad"),
                    "categoria": payload.categoria.strip(),
                    "subcategoria": (payload.subcategoria.strip() if payload.subcategoria else None),
                    "color": (payload.color.strip() if payload.color else None),
                    "descripcion": (payload.descripcion.strip() if payload.descripcion else None),
                    "tamano": (payload.tamano.strip() if payload.tamano else None),
                    "fecha_vencimiento": payload.fechaVencimiento,
                    "marca": (payload.marca.strip() if payload.marca else None),
                    "precio_venta": payload.precioVenta,
                    "activo": bool(payload.activo),
                    "created_at": now,
                    "updated_at": now,
                    "proveedor_id": (int(payload.proveedorID) if payload.proveedorID is not None else None),
                },
            ).first()
        elif has_cat:
            # Primera migración aplicada (categoria, subcategoria, etc.) pero no marca/precio_venta
            insumo_row = db.execute(
                text(
                    """
                    INSERT INTO petalops.insumo (
                        empresa_id, codigo_barra, nombre_insumo, unidad_medida,
                        categoria, subcategoria, color, descripcion, tamano,
                        fecha_vencimiento, activo, created_at, updated_at, proveedor_id
                    ) VALUES (
                        :empresa_id, :codigo_barra, :nombre_insumo, :unidad_medida,
                        :categoria, :subcategoria, :color, :descripcion, :tamano,
                        :fecha_vencimiento, :activo, :created_at, :updated_at, :proveedor_id
                    )
                    RETURNING id_insumo
                    """
                ),
                {
                    "empresa_id": int(payload.empresaID),
                    "codigo_barra": payload.codigo.strip(),
                    "nombre_insumo": payload.nombre.strip(),
                    "unidad_medida": (payload.unidadMedida.strip() if payload.unidadMedida else "Unidad"),
                    "categoria": payload.categoria.strip(),
                    "subcategoria": (payload.subcategoria.strip() if payload.subcategoria else None),
                    "color": (payload.color.strip() if payload.color else None),
                    "descripcion": (payload.descripcion.strip() if payload.descripcion else None),
                    "tamano": (payload.tamano.strip() if payload.tamano else None),
                    "fecha_vencimiento": payload.fechaVencimiento,
                    "activo": bool(payload.activo),
                    "created_at": now,
                    "updated_at": now,
                    "proveedor_id": (int(payload.proveedorID) if payload.proveedorID is not None else None),
                },
            ).first()
        else:
            # Sin migraciones: solo campos base
            insumo_row = db.execute(
                text(
                    """
                    INSERT INTO petalops.insumo (
                        empresa_id, codigo_barra, nombre_insumo,
                        unidad_medida, activo, created_at, updated_at, proveedor_id
                    ) VALUES (
                        :empresa_id, :codigo_barra, :nombre_insumo,
                        :unidad_medida, :activo, :created_at, :updated_at, :proveedor_id
                    )
                    RETURNING id_insumo
                    """
                ),
                {
                    "empresa_id": int(payload.empresaID),
                    "codigo_barra": payload.codigo.strip(),
                    "nombre_insumo": payload.nombre.strip(),
                    "unidad_medida": payload.categoria.strip(),
                    "activo": bool(payload.activo),
                    "created_at": now,
                    "updated_at": now,
                    "proveedor_id": (int(payload.proveedorID) if payload.proveedorID is not None else None),
                },
            ).first()

        insumo_id = int(insumo_row[0])

        item_row = db.execute(
            text(
                """
                INSERT INTO petalops.inventario (
                    empresa_id, sucursal_id, insumo_id,
                    stock_actual, stock_reservado, stock_minimo,
                    valor_unitario, activo, fechaultimaactualizacion,
                    created_at, updated_at
                ) VALUES (
                    :empresa_id, :sucursal_id, :insumo_id,
                    :stock_actual, :stock_reservado, :stock_minimo,
                    :valor_unitario, :activo, :fecha_actualizacion,
                    :created_at, :updated_at
                )
                RETURNING id_inventario
                """
            ),
            {
                "empresa_id": int(payload.empresaID),
                "sucursal_id": int(auth.sucursalID),
                "insumo_id": insumo_id,
                "stock_actual": payload.stockActual,
                "stock_reservado": Decimal("0"),
                "stock_minimo": payload.stockMinimo,
                "valor_unitario": payload.valorUnitario,
                "activo": bool(payload.activo),
                "fecha_actualizacion": now,
                "created_at": now,
                "updated_at": now,
            },
        ).first()
        inventario_id = int(item_row[0])

        if Decimal(payload.stockActual) > 0:
            tipo_movimiento_id = _resolve_movimiento_tipo_id(db, "Entrada")
            db.execute(
                text(
                    """
                    INSERT INTO petalops.movimiento_inventario (
                        empresa_id, inventario_id, tipo_movimiento_id,
                        cantidad, fecha, motivo, usuario_id, created_at
                    ) VALUES (
                        :empresa_id, :inventario_id, :tipo_movimiento_id,
                        :cantidad, :fecha, :motivo, :usuario_id, :created_at
                    )
                    """
                ),
                {
                    "empresa_id": int(payload.empresaID),
                    "inventario_id": inventario_id,
                    "tipo_movimiento_id": tipo_movimiento_id,
                    "cantidad": Decimal(payload.stockActual),
                    "fecha": now,
                    "motivo": "Carga inicial",
                    "usuario_id": int(auth.userID),
                    "created_at": now,
                },
            )

        db.commit()
        item = db.query(Inventario).filter(Inventario.idInventario == inventario_id).first()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=400, detail="No fue posible crear item de inventario (codigo duplicado o datos invalidos)")

    return InventarioMutationResponse(status="ok", item=_to_item_from_db(db, item))


@router.put("/{inventario_id}", response_model=InventarioMutationResponse, dependencies=[Depends(require_module_access("inventario", "puedeEditar"))])
def actualizar_item_inventario(
    inventario_id: int,
    payload: InventarioUpdateRequest,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    item = db.query(Inventario).filter(Inventario.idInventario == inventario_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item no encontrado")

    assert_same_empresa(auth, int(item.empresaID))
    insumo = db.query(Insumo).filter(Insumo.idInsumo == int(item.insumoID), Insumo.empresaID == int(item.empresaID)).first()
    if not insumo:
        raise HTTPException(status_code=404, detail="Insumo asociado no encontrado")

    if payload.proveedorID is not None:
        proveedor = _get_proveedor_for_empresa(db, int(item.empresaID), int(payload.proveedorID))
        if not proveedor:
            raise HTTPException(status_code=400, detail="Proveedor no valido para la empresa")

    has_cat   = _has_column(db, "insumo", "categoria")
    has_marca = has_cat and _has_column(db, "insumo", "marca")
    now = datetime.now(timezone.utc)

    insumo.nombreInsumo = payload.nombre.strip()
    insumo.proveedorID = (int(payload.proveedorID) if payload.proveedorID is not None else None)
    insumo.updatedAt = now
    insumo.activo = bool(item.activo)

    if has_cat:
        insumo.categoria = payload.categoria.strip()
        insumo.subcategoria = (payload.subcategoria.strip() if payload.subcategoria else None)
        insumo.color = (payload.color.strip() if payload.color else None)
        insumo.descripcion = (payload.descripcion.strip() if payload.descripcion else None)
        insumo.tamano = (payload.tamano.strip() if payload.tamano else None)
        insumo.fechaVencimiento = payload.fechaVencimiento
        if payload.unidadMedida:
            insumo.unidadMedida = payload.unidadMedida.strip()
    else:
        insumo.unidadMedida = payload.categoria.strip()

    if has_marca:
        insumo.marca = (payload.marca.strip() if payload.marca else None)
        insumo.precioVenta = payload.precioVenta

    item.stockMinimo = payload.stockMinimo
    item.valorUnitario = payload.valorUnitario
    item.fechaUltimaActualizacion = now
    item.updatedAt = now

    try:
        db.commit()
        db.refresh(item)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=400, detail="No fue posible actualizar item de inventario")

    return InventarioMutationResponse(status="ok", item=_to_item_from_db(db, item))


@router.put("/{inventario_id}/stock", response_model=InventarioMutationResponse, dependencies=[Depends(require_module_access("inventario", "puedeEditar"))])
def ajustar_stock_inventario(
    inventario_id: int,
    payload: InventarioStockAdjustRequest,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    item = db.query(Inventario).filter(Inventario.idInventario == inventario_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item no encontrado")

    assert_same_empresa(auth, int(item.empresaID))

    movimiento_tipo = _normalize_movimiento_tipo(payload.tipoMovimiento)
    movimiento_tipo_id = _resolve_movimiento_tipo_id(db, movimiento_tipo)
    cantidad = Decimal(payload.cantidad or 0)
    now = datetime.now(timezone.utc)

    stock_actual = Decimal(item.stockActual or 0)

    if movimiento_tipo == "Entrada":
        if cantidad <= 0:
            raise HTTPException(status_code=400, detail="cantidad debe ser mayor a 0 para Entrada")
        nuevo_stock = stock_actual + cantidad
        cantidad_mov = cantidad
    elif _movement_tipo_key(movimiento_tipo) == "perdida":
        if cantidad <= 0:
            raise HTTPException(status_code=400, detail="cantidad debe ser mayor a 0 para Perdida")
        nuevo_stock = stock_actual - cantidad
        if nuevo_stock < 0:
            raise HTTPException(status_code=400, detail="No se permite stock negativo")
        cantidad_mov = cantidad
    elif movimiento_tipo in ("Salida", "Pérdida"):
        if cantidad <= 0:
            raise HTTPException(status_code=400, detail=f"cantidad debe ser mayor a 0 para {movimiento_tipo}")
        nuevo_stock = stock_actual - cantidad
        if nuevo_stock < 0:
            raise HTTPException(status_code=400, detail="No se permite stock negativo")
        cantidad_mov = cantidad
    else:  # Ajuste
        if payload.stockObjetivo is None:
            raise HTTPException(status_code=400, detail="stockObjetivo es obligatorio para Ajuste")
        objetivo = Decimal(payload.stockObjetivo)
        if objetivo < 0:
            raise HTTPException(status_code=400, detail="No se permite stock negativo")
        nuevo_stock = objetivo
        cantidad_mov = abs(nuevo_stock - stock_actual)

    item.stockActual = nuevo_stock
    item.fechaUltimaActualizacion = now
    item.updatedAt = now

    movimiento = MovimientoInventario(
        empresaID=int(item.empresaID),
        inventarioID=int(item.idInventario),
        tipoMovimiento=movimiento_tipo_id,
        cantidad=cantidad_mov,
        fecha=now,
        motivo=payload.motivo.strip(),
        usuarioID=int(auth.userID),
        createdAt=now,
        estado="Registrado",
        stockAnterior=stock_actual,
        stockNuevo=nuevo_stock,
    )
    db.add(movimiento)

    try:
        db.commit()
        db.refresh(item)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=400, detail="No fue posible ajustar stock")

    return InventarioMutationResponse(status="ok", item=_to_item_from_db(db, item))


@router.post("/compras", response_model=InventarioMutationResponse, dependencies=[Depends(require_module_access("inventario", "puedeEditar"))])
def registrar_compra_inventario(
    payload: InventarioCompraRequest,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    item = db.query(Inventario).filter(Inventario.idInventario == int(payload.inventarioID)).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item no encontrado")
    assert_same_empresa(auth, int(item.empresaID))

    if payload.proveedorID is not None:
        proveedor = _get_proveedor_for_empresa(db, int(item.empresaID), int(payload.proveedorID))
        if not proveedor:
            raise HTTPException(status_code=400, detail="Proveedor no valido para la empresa")

    insumo = db.query(Insumo).filter(Insumo.idInsumo == int(item.insumoID), Insumo.empresaID == int(item.empresaID)).first()
    if insumo and payload.fechaVencimiento and _has_column(db, "insumo", "fecha_vencimiento"):
        insumo.fechaVencimiento = payload.fechaVencimiento
        insumo.updatedAt = datetime.now(timezone.utc)
    if insumo and payload.proveedorID is not None:
        insumo.proveedorID = int(payload.proveedorID)
        insumo.updatedAt = datetime.now(timezone.utc)

    motivo = _movement_note(
        "Compra registrada",
        {
            "factura": payload.numeroFactura,
            "proveedorID": payload.proveedorID,
            "responsable": payload.responsable,
            "unidad": payload.unidad,
            "precioUnitario": payload.precioUnitario,
            "calidad": payload.calidad,
            "estadoRecibido": payload.estadoRecibido,
            "vencimiento": payload.fechaVencimiento,
            "observaciones": payload.observaciones,
        },
    )
    _apply_stock_movement(
        db=db,
        auth=auth,
        item=item,
        tipo_movimiento="Entrada",
        cantidad=payload.cantidad,
        fecha=payload.fecha,
        motivo=motivo,
        proveedor_id=payload.proveedorID,
        numero_factura=payload.numeroFactura,
        responsable=payload.responsable,
        unidad=payload.unidad,
        precio_unitario=payload.precioUnitario,
        fecha_vencimiento=payload.fechaVencimiento,
        observaciones=payload.observaciones,
    )

    try:
        db.commit()
        db.refresh(item)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=400, detail="No fue posible registrar compra")

    return InventarioMutationResponse(status="ok", item=_to_item_from_db(db, item))


@router.post("/danos", response_model=InventarioMutationResponse, dependencies=[Depends(require_module_access("inventario", "puedeEditar"))])
def registrar_dano_inventario(
    payload: InventarioDanoRequest,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    item = db.query(Inventario).filter(Inventario.idInventario == int(payload.inventarioID)).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item no encontrado")

    motivo = _movement_note(
        "Daño registrado",
        {
            "motivo": payload.motivo,
            "responsable": payload.responsable,
            "unidad": payload.unidad,
            "evidencia": payload.evidenciaUrl,
            "pedido": payload.pedidoReferencia,
            "observaciones": payload.observaciones,
        },
    )
    _apply_stock_movement(
        db=db,
        auth=auth,
        item=item,
        tipo_movimiento="perdida",
        cantidad=payload.cantidad,
        fecha=payload.fecha,
        motivo=motivo,
        responsable=payload.responsable,
        unidad=payload.unidad,
        evidencia_url=payload.evidenciaUrl,
        pedido_referencia=payload.pedidoReferencia,
        observaciones=payload.observaciones,
    )

    try:
        db.commit()
        db.refresh(item)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=400, detail="No fue posible registrar daño")

    return InventarioMutationResponse(status="ok", item=_to_item_from_db(db, item))


@router.put("/{inventario_id}/activo", response_model=InventarioMutationResponse, dependencies=[Depends(require_module_access("inventario", "puedeEditar"))])
def actualizar_activo_inventario(
    inventario_id: int,
    payload: InventarioActivoRequest,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    item = db.query(Inventario).filter(Inventario.idInventario == inventario_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item no encontrado")

    assert_same_empresa(auth, int(item.empresaID))

    now = datetime.now(timezone.utc)
    item.activo = bool(payload.activo)
    item.fechaUltimaActualizacion = now
    item.updatedAt = now
    insumo = db.query(Insumo).filter(Insumo.idInsumo == int(item.insumoID), Insumo.empresaID == int(item.empresaID)).first()
    if insumo:
        insumo.activo = bool(payload.activo)
        insumo.updatedAt = now

    try:
        db.commit()
        db.refresh(item)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=400, detail="No fue posible actualizar estado del item")

    return InventarioMutationResponse(status="ok", item=_to_item_from_db(db, item))


@router.get("/movimientos", response_model=MovimientoInventarioListResponse)
def listar_movimientos_inventario(
    empresa_id: int = Query(..., alias="empresaID"),
    inventario_id: int | None = Query(None, alias="inventarioID"),
    tipo: str | None = Query(None),
    categoria: str | None = Query(None, alias="modulo"),
    fecha_desde: date | None = Query(None, alias="fechaDesde"),
    fecha_hasta: date | None = Query(None, alias="fechaHasta"),
    usuario_id: int | None = Query(None, alias="usuarioID"),
    estado: str | None = Query(None),
    q: str | None = Query(None),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)
    query = (
        db.query(MovimientoInventario, Inventario, Insumo)
        .join(Inventario, Inventario.idInventario == MovimientoInventario.inventarioID)
        .outerjoin(Insumo, Insumo.idInsumo == Inventario.insumoID)
        .filter(MovimientoInventario.empresaID == empresa_id)
    )
    has_categoria_col = _has_column(db, "insumo", "categoria")

    if inventario_id is not None:
        query = query.filter(MovimientoInventario.inventarioID == inventario_id)

    if tipo:
        tipo_id = _resolve_movimiento_tipo_id(db, tipo)
        query = query.filter(MovimientoInventario.tipoMovimiento == tipo_id)

    if categoria:
        query = query.filter(func.upper(_categoria_expr(has_categoria_col)) == str(categoria).strip().upper())

    if fecha_desde:
        query = query.filter(MovimientoInventario.fecha >= datetime.combine(fecha_desde, datetime.min.time()))

    if fecha_hasta:
        query = query.filter(MovimientoInventario.fecha <= datetime.combine(fecha_hasta, datetime.max.time()))

    if usuario_id is not None:
        query = query.filter(MovimientoInventario.usuarioID == int(usuario_id))

    if estado and str(estado).strip().lower() not in {"todos", "todo"}:
        query = query.filter(func.lower(MovimientoInventario.estado) == str(estado).strip().lower())

    if q:
        term = f"%{q.strip()}%"
        query = query.filter(
            Insumo.nombreInsumo.ilike(term)
            | Insumo.codigoBarra.ilike(term)
            | MovimientoInventario.motivo.ilike(term)
        )

    rows = query.order_by(MovimientoInventario.fecha.desc(), MovimientoInventario.idMovimiento.desc()).all()

    items = [_movimiento_item_response(mov, inv, ins, has_categoria_col=has_categoria_col) for mov, inv, ins in rows]
    return MovimientoInventarioListResponse(items=items, total=len(items))


@router.get("/movimientos/metricas", response_model=MovimientoInventarioMetricasResponse)
def obtener_metricas_movimientos_inventario(
    empresa_id: int = Query(..., alias="empresaID"),
    categoria: str | None = Query(None, alias="modulo"),
    fecha_desde: date | None = Query(None, alias="fechaDesde"),
    fecha_hasta: date | None = Query(None, alias="fechaHasta"),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)

    query = (
        db.query(MovimientoInventario, Inventario, Insumo)
        .join(Inventario, Inventario.idInventario == MovimientoInventario.inventarioID)
        .outerjoin(Insumo, Insumo.idInsumo == Inventario.insumoID)
        .filter(MovimientoInventario.empresaID == int(empresa_id))
        .filter(func.lower(MovimientoInventario.estado) != "anulado")
    )
    has_categoria_col = _has_column(db, "insumo", "categoria")
    if categoria:
        query = query.filter(func.upper(_categoria_expr(has_categoria_col)) == str(categoria).strip().upper())
    if fecha_desde:
        query = query.filter(MovimientoInventario.fecha >= datetime.combine(fecha_desde, datetime.min.time()))
    if fecha_hasta:
        query = query.filter(MovimientoInventario.fecha <= datetime.combine(fecha_hasta, datetime.max.time()))

    entradas = Decimal("0")
    salidas = Decimal("0")
    ajustes = Decimal("0")
    danos = Decimal("0")
    total_hoy = 0
    today = date.today()

    for mov, _inv, _ins in query.all():
        tipo = _movimiento_tipo_label(mov.tipoMovimiento).lower()
        cantidad = Decimal(mov.cantidad or 0)
        if tipo == "entrada":
            entradas += cantidad
        elif tipo == "salida":
            salidas += cantidad
        elif tipo == "ajuste":
            ajustes += cantidad
        else:
            danos += cantidad
        if mov.fecha and mov.fecha.date() == today:
            total_hoy += 1

    return MovimientoInventarioMetricasResponse(
        entradas=entradas,
        salidas=salidas,
        ajustes=ajustes,
        danos=danos,
        totalHoy=total_hoy,
    )


@router.get("/compras", response_model=MovimientoInventarioListResponse)
def listar_compras_inventario(
    empresa_id: int = Query(..., alias="empresaID"),
    inventario_id: int | None = Query(None, alias="inventarioID"),
    fecha_desde: date | None = Query(None, alias="fechaDesde"),
    fecha_hasta: date | None = Query(None, alias="fechaHasta"),
    q: str | None = Query(None),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)
    entrada_id = _resolve_movimiento_tipo_id(db, "Entrada")
    query = (
        db.query(MovimientoInventario, Inventario, Insumo)
        .join(Inventario, Inventario.idInventario == MovimientoInventario.inventarioID)
        .outerjoin(Insumo, Insumo.idInsumo == Inventario.insumoID)
        .filter(
            MovimientoInventario.empresaID == int(empresa_id),
            MovimientoInventario.tipoMovimiento == entrada_id,
            func.lower(MovimientoInventario.estado) != "anulado",
        )
        .filter(
            (MovimientoInventario.numeroFactura.isnot(None))
            | (MovimientoInventario.proveedorID.isnot(None))
            | (MovimientoInventario.motivo.ilike("Compra registrada%"))
        )
    )
    if inventario_id is not None:
        query = query.filter(MovimientoInventario.inventarioID == int(inventario_id))
    if fecha_desde:
        query = query.filter(MovimientoInventario.fecha >= datetime.combine(fecha_desde, datetime.min.time()))
    if fecha_hasta:
        query = query.filter(MovimientoInventario.fecha <= datetime.combine(fecha_hasta, datetime.max.time()))
    if q:
        term = f"%{q.strip()}%"
        query = query.filter(
            Insumo.nombreInsumo.ilike(term)
            | Insumo.codigoBarra.ilike(term)
            | MovimientoInventario.numeroFactura.ilike(term)
            | MovimientoInventario.motivo.ilike(term)
        )

    has_categoria_col = _has_column(db, "insumo", "categoria")
    rows = query.order_by(MovimientoInventario.fecha.desc(), MovimientoInventario.idMovimiento.desc()).all()
    items = [_movimiento_item_response(mov, inv, ins, has_categoria_col=has_categoria_col) for mov, inv, ins in rows]
    return MovimientoInventarioListResponse(items=items, total=len(items))


@router.post("/movimientos/{movimiento_id}/anular", response_model=InventarioMutationResponse, dependencies=[Depends(require_module_access("inventario", "puedeEditar"))])
def anular_movimiento_inventario(
    movimiento_id: int,
    payload: MovimientoInventarioAnularRequest,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    mov = (
        db.query(MovimientoInventario)
        .filter(MovimientoInventario.idMovimiento == int(movimiento_id))
        .with_for_update()
        .first()
    )
    if not mov:
        raise HTTPException(status_code=404, detail="Movimiento no encontrado")
    assert_same_empresa(auth, int(mov.empresaID))
    if _movement_estado(getattr(mov, "estado", None)).lower() == "anulado":
        raise HTTPException(status_code=409, detail="El movimiento ya esta anulado")
    if getattr(mov, "movimientoOrigenID", None) is not None:
        raise HTTPException(status_code=409, detail="No se puede anular un movimiento de reverso")

    item = (
        db.query(Inventario)
        .filter(Inventario.idInventario == int(mov.inventarioID))
        .with_for_update()
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Item de inventario no encontrado")

    now = datetime.now(timezone.utc)
    stock_actual = Decimal(item.stockActual or 0)
    cantidad = Decimal(mov.cantidad or 0)
    tipo_key = _movement_tipo_key(mov.tipoMovimiento)

    if tipo_key == "entrada":
        nuevo_stock = stock_actual - cantidad
        if nuevo_stock < 0:
            raise HTTPException(status_code=409, detail="No se puede anular porque generaria stock negativo")
    elif tipo_key in {"salida", "perdida"}:
        nuevo_stock = stock_actual + cantidad
    elif tipo_key == "ajuste":
        if getattr(mov, "stockAnterior", None) is None:
            raise HTTPException(status_code=409, detail="Este ajuste no tiene stock anterior registrado")
        nuevo_stock = Decimal(mov.stockAnterior or 0)
        cantidad = abs(nuevo_stock - stock_actual)
    else:
        raise HTTPException(status_code=400, detail="Tipo de movimiento no soportado para anulacion")

    mov.estado = "Anulado"
    mov.anuladoAt = now
    mov.anuladoPorUsuarioID = int(auth.userID)
    mov.motivoAnulacion = payload.motivo.strip()

    item.stockActual = nuevo_stock
    item.fechaUltimaActualizacion = now
    item.updatedAt = now

    ajuste_id = _resolve_movimiento_tipo_id(db, "Ajuste")
    db.add(
        MovimientoInventario(
            empresaID=int(item.empresaID),
            inventarioID=int(item.idInventario),
            tipoMovimiento=ajuste_id,
            cantidad=cantidad,
            fecha=now,
            motivo=_movement_note("Anulacion de movimiento", {"referencia": _movement_referencia(mov), "motivo": payload.motivo}),
            usuarioID=int(auth.userID),
            createdAt=now,
            estado="Registrado",
            stockAnterior=stock_actual,
            stockNuevo=nuevo_stock,
            referencia=f"ANU-{int(mov.idMovimiento)}",
            movimientoOrigenID=int(mov.idMovimiento),
            observaciones=payload.motivo.strip(),
        )
    )

    try:
        db.commit()
        db.refresh(item)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=400, detail="No fue posible anular el movimiento")

    return InventarioMutationResponse(status="ok", item=_to_item_from_db(db, item))


def _pdf_line(canvas_obj, y: float, label: str, value: object | None) -> float:
    canvas_obj.setFont("Helvetica-Bold", 9)
    canvas_obj.drawString(18 * mm, y, f"{label}:")
    canvas_obj.setFont("Helvetica", 9)
    canvas_obj.drawString(58 * mm, y, str(value if value is not None else ""))
    return y - 7 * mm


@router.get("/movimientos/{movimiento_id}/pdf", dependencies=[Depends(require_module_access("inventario", "puedeVer"))])
def imprimir_movimiento_inventario(
    movimiento_id: int,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    row = (
        db.query(MovimientoInventario, Inventario, Insumo)
        .join(Inventario, Inventario.idInventario == MovimientoInventario.inventarioID)
        .outerjoin(Insumo, Insumo.idInsumo == Inventario.insumoID)
        .filter(MovimientoInventario.idMovimiento == int(movimiento_id))
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Movimiento no encontrado")
    mov, inv, ins = row
    assert_same_empresa(auth, int(mov.empresaID))

    from io import BytesIO

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    y = height - 22 * mm
    pdf.setTitle(f"Movimiento inventario {_movement_referencia(mov)}")
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(18 * mm, y, "Movimiento de inventario")
    y -= 12 * mm
    pdf.setFont("Helvetica", 10)
    pdf.drawString(18 * mm, y, f"Referencia: {_movement_referencia(mov)}")
    y -= 12 * mm

    data = _movimiento_item_response(mov, inv, ins, has_categoria_col=_has_column(db, "insumo", "categoria"))
    campos = [
        ("Movimiento", data.movimientoID),
        ("Estado", data.estado),
        ("Tipo", data.tipoMovimiento),
        ("Fecha", data.fecha),
        ("Codigo", data.codigo),
        ("Item", data.nombre),
        ("Categoria", data.categoria),
        ("Cantidad", data.cantidad),
        ("Stock anterior", data.stockAnterior),
        ("Stock nuevo", data.stockNuevo),
        ("Factura", data.numeroFactura),
        ("Proveedor", data.proveedorID),
        ("Responsable", data.responsable),
        ("Evidencia", data.evidenciaUrl),
        ("Pedido ref.", data.pedidoReferencia),
        ("Motivo", data.motivo),
        ("Anulado por", data.anuladoPorUsuarioID),
        ("Motivo anulacion", data.motivoAnulacion),
    ]
    for label, value in campos:
        if y < 24 * mm:
            pdf.showPage()
            y = height - 22 * mm
        y = _pdf_line(pdf, y, label, value)
    pdf.setFont("Helvetica", 8)
    pdf.drawRightString(width - 18 * mm, 14 * mm, f"Generado: {datetime.now(timezone.utc).isoformat()}")
    pdf.save()
    content = buffer.getvalue()
    filename = f"movimiento-inventario-{int(mov.idMovimiento)}.pdf"
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Arreglos / Recetas
# ---------------------------------------------------------------------------

def _producto_precio_imagen(db: Session, producto_id: int | None, sucursal_id: int | None) -> dict:
    """Precio/imagen del producto vinculado a una receta, para la sucursal
    actual (petalops.producto_sucursal). No depende del ORM porque el modelo
    Producto declara una FK a categoria desactualizada frente a la BD real."""
    if not producto_id:
        return {"codigoProducto": None, "precioVenta": None, "imagenUrl": None}
    row = db.execute(
        text(
            """
            SELECT p.codigo_producto AS codigo_producto, ps.precio AS precio, ps.imagen_url AS imagen_url
            FROM petalops.producto p
            LEFT JOIN petalops.producto_sucursal ps
              ON ps.producto_id = p.id_producto
             AND ps.sucursal_id = :sucursal_id
            WHERE p.id_producto = :producto_id
            """
        ),
        {"producto_id": int(producto_id), "sucursal_id": int(sucursal_id or 0)},
    ).mappings().first()
    if not row:
        return {"codigoProducto": None, "precioVenta": None, "imagenUrl": None}
    return {
        "codigoProducto": row["codigo_producto"],
        "precioVenta": Decimal(row["precio"]) if row["precio"] is not None else None,
        "imagenUrl": row["imagen_url"],
    }


def _ventas_receta(db: Session, empresa_id: int, producto_id: int | None) -> dict:
    """Vendidos hoy (pedidos APROBADO creados hoy) y reservados (pedidos
    APROBADO cuya entrega todavia no llega a estado 'entregado'/'cancelado')
    para el producto vinculado a esta receta."""
    if not producto_id:
        return {"vendidosHoy": Decimal("0"), "reservados": Decimal("0")}
    row = db.execute(
        text(
            """
            SELECT
              COALESCE(SUM(pd.cantidad) FILTER (
                WHERE UPPER(ep.nombre_estado) = 'APROBADO'
                  AND DATE(pe.fecha_pedido) = CURRENT_DATE
              ), 0) AS vendidos_hoy,
              COALESCE(SUM(pd.cantidad) FILTER (
                WHERE UPPER(ep.nombre_estado) = 'APROBADO'
                  AND (ee.codigo IS NULL OR ee.codigo NOT IN ('entregado', 'cancelado'))
              ), 0) AS reservados
            FROM petalops.pedido_detalle pd
            JOIN petalops.pedido pe ON pe.id_pedido = pd.pedido_id
            JOIN petalops.estado_pedido ep ON ep.id_estado_pedido = pe.estado_pedido_id
            LEFT JOIN petalops.entrega en ON en.pedido_id = pe.id_pedido
            LEFT JOIN petalops.estado_entrega ee ON ee.id_estado_entrega = en.estadoentregaid
            WHERE pd.empresa_id = :empresa_id
              AND pd.producto_id = :producto_id
            """
        ),
        {"empresa_id": int(empresa_id), "producto_id": int(producto_id)},
    ).mappings().first()
    if not row:
        return {"vendidosHoy": Decimal("0"), "reservados": Decimal("0")}
    return {
        "vendidosHoy": Decimal(row["vendidos_hoy"] or 0),
        "reservados": Decimal(row["reservados"] or 0),
    }


def _obtener_o_crear_categoria_arreglos(db: Session, empresa_id: int) -> int:
    row = db.execute(
        text("SELECT id_categoria FROM petalops.categoria WHERE empresa_id = :empresa_id AND nombre ILIKE 'Arreglos' LIMIT 1"),
        {"empresa_id": int(empresa_id)},
    ).first()
    if row:
        return int(row[0])
    row = db.execute(
        text(
            """
            INSERT INTO petalops.categoria (empresa_id, nombre, created_at, activo)
            VALUES (:empresa_id, 'Arreglos', now(), true)
            RETURNING id_categoria
            """
        ),
        {"empresa_id": int(empresa_id)},
    ).first()
    return int(row[0])


def _crear_producto_para_receta(
    db: Session,
    *,
    empresa_id: int,
    sucursal_id: int | None,
    nombre: str,
    descripcion: str | None,
    precio: Decimal,
    imagen_url: str | None,
) -> int:
    categoria_id = _obtener_o_crear_categoria_arreglos(db, empresa_id)
    now = datetime.now(timezone.utc)
    base_slug = re.sub(r"[^A-Z0-9]+", "", nombre.strip().upper())[:12] or "ARR"
    codigo_producto = f"ARR-{base_slug}-{secrets.token_hex(3).upper()}"
    row = db.execute(
        text(
            """
            INSERT INTO petalops.producto (
              empresa_id, categoria_id, codigo_producto, nombre_producto, descripcion,
              porcentaje_iva, iva_incluido, activo, created_at, updated_at
            )
            VALUES (
              :empresa_id, :categoria_id, :codigo_producto, :nombre, :descripcion,
              0, true, true, :now, :now
            )
            RETURNING id_producto
            """
        ),
        {
            "empresa_id": int(empresa_id),
            "categoria_id": categoria_id,
            "codigo_producto": codigo_producto,
            "nombre": nombre.strip(),
            "descripcion": (descripcion.strip() if descripcion else None),
            "now": now,
        },
    ).first()
    producto_id = int(row[0])

    if sucursal_id:
        db.execute(
            text(
                """
                INSERT INTO petalops.producto_sucursal (
                  producto_id, sucursal_id, precio, imagen_url, activo, created_at, updated_at
                )
                VALUES (:producto_id, :sucursal_id, :precio, :imagen_url, true, :now, :now)
                """
            ),
            {
                "producto_id": producto_id,
                "sucursal_id": int(sucursal_id),
                "precio": precio,
                "imagen_url": imagen_url,
                "now": now,
            },
        )
    return producto_id


def _invalidate_catalogo_cache(empresa_id: int, sucursal_id: int | None) -> None:
    """Limpia el caché de /catalogo tras crear un producto nuevo via receta (ver cache-fase1)."""
    if not sucursal_id:
        return
    invalidate_cache_prefix(f"catalogo:{int(empresa_id)}:sucursal:{int(sucursal_id)}")


def _receta_item_extra(db: Session, rec: Receta, sucursal_id: int | None) -> dict:
    precio_info = _producto_precio_imagen(db, rec.productoID, sucursal_id)
    ventas_info = _ventas_receta(db, int(rec.empresaID), rec.productoID)
    return {
        "productoID": (int(rec.productoID) if rec.productoID else None),
        "capacidadManual": (Decimal(rec.capacidadManual) if rec.capacidadManual is not None else None),
        **precio_info,
        **ventas_info,
    }


@router.get("/recetas", response_model=RecetaListResponse)
def listar_recetas(
    empresa_id: int = Query(..., alias="empresaID"),
    q: str | None = Query(None),
    solo_activos: bool = Query(True, alias="soloActivos"),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)

    query = db.query(Receta).filter(Receta.empresaID == empresa_id)
    if solo_activos:
        query = query.filter(Receta.activo == True)  # noqa: E712
    if q:
        term = f"%{q.strip()}%"
        query = query.filter(Receta.nombre.ilike(term) | Receta.descripcion.ilike(term))

    rows = query.order_by(Receta.nombre.asc()).all()

    items = []
    for rec in rows:
        total = db.query(RecetaDetalle).filter(RecetaDetalle.recetaID == int(rec.idReceta)).count()
        extra = _receta_item_extra(db, rec, auth.sucursalID)
        items.append(
            RecetaListItem(
                idReceta=int(rec.idReceta),
                empresaID=int(rec.empresaID),
                nombre=str(rec.nombre),
                descripcion=(str(rec.descripcion) if rec.descripcion else None),
                activo=bool(rec.activo),
                totalIngredientes=total,
                **extra,
            )
        )
    return RecetaListResponse(items=items, total=len(items))


@router.post("/recetas", response_model=RecetaItem, dependencies=[Depends(require_module_access("inventario", "puedeCrear"))])
def crear_receta(
    payload: RecetaCreateRequest,
    empresa_id: int = Query(..., alias="empresaID"),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)

    producto_id = payload.productoID
    producto_nuevo_sucursal_id: int | None = None
    if producto_id is not None:
        existe = db.execute(
            text("SELECT 1 FROM petalops.producto WHERE id_producto = :id AND empresa_id = :empresa_id"),
            {"id": int(producto_id), "empresa_id": int(empresa_id)},
        ).first()
        if not existe:
            raise HTTPException(status_code=400, detail="Producto no válido para esta empresa")
    elif payload.precioVenta is not None:
        producto_id = _crear_producto_para_receta(
            db,
            empresa_id=empresa_id,
            sucursal_id=auth.sucursalID,
            nombre=payload.nombre,
            descripcion=payload.descripcion,
            precio=payload.precioVenta,
            imagen_url=payload.imagenUrl,
        )
        producto_nuevo_sucursal_id = auth.sucursalID

    now = datetime.now(timezone.utc)
    try:
        rec = Receta(
            empresaID=int(empresa_id),
            nombre=payload.nombre.strip(),
            descripcion=(payload.descripcion.strip() if payload.descripcion else None),
            productoID=producto_id,
            capacidadManual=payload.capacidadManual,
            activo=True,
            createdAt=now,
            updatedAt=now,
        )
        db.add(rec)
        db.commit()
        db.refresh(rec)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=400, detail="No fue posible crear receta (nombre duplicado)")

    # Producto recien creado y comiteado: invalidar catalogo cacheado para que aparezca sin esperar el TTL.
    _invalidate_catalogo_cache(empresa_id, producto_nuevo_sucursal_id)

    extra = _receta_item_extra(db, rec, auth.sucursalID)
    return RecetaItem(
        idReceta=int(rec.idReceta),
        empresaID=int(rec.empresaID),
        nombre=str(rec.nombre),
        descripcion=(str(rec.descripcion) if rec.descripcion else None),
        activo=bool(rec.activo),
        detalles=[],
        **extra,
    )


@router.get("/recetas/{receta_id}", response_model=RecetaItem)
def obtener_receta(
    receta_id: int,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    rec = db.query(Receta).filter(Receta.idReceta == receta_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Receta no encontrada")
    assert_same_empresa(auth, int(rec.empresaID))

    detalles_rows = (
        db.query(RecetaDetalle, Inventario, Insumo)
        .join(Inventario, Inventario.idInventario == RecetaDetalle.inventarioID)
        .outerjoin(Insumo, Insumo.idInsumo == Inventario.insumoID)
        .filter(RecetaDetalle.recetaID == receta_id)
        .all()
    )

    has_cat = _has_column(db, "insumo", "categoria")
    detalles = [
        RecetaDetalleItem(
            idRecetaDetalle=int(det.idRecetaDetalle),
            inventarioID=int(det.inventarioID),
            codigo=(str(ins.codigoBarra) if ins and ins.codigoBarra else f"INS-{int(inv.insumoID)}"),
            nombre=(str(ins.nombreInsumo) if ins and ins.nombreInsumo else f"Insumo {int(inv.insumoID)}"),
            categoria=(str(ins.categoria) if ins and has_cat and ins.categoria else (str(ins.unidadMedida) if ins and ins.unidadMedida else None)),
            cantidad=Decimal(det.cantidad or 1),
        )
        for det, inv, ins in detalles_rows
    ]

    extra = _receta_item_extra(db, rec, auth.sucursalID)
    return RecetaItem(
        idReceta=int(rec.idReceta),
        empresaID=int(rec.empresaID),
        nombre=str(rec.nombre),
        descripcion=(str(rec.descripcion) if rec.descripcion else None),
        activo=bool(rec.activo),
        detalles=detalles,
        **extra,
    )


@router.put("/recetas/{receta_id}", response_model=RecetaItem, dependencies=[Depends(require_module_access("inventario", "puedeEditar"))])
def actualizar_receta(
    receta_id: int,
    payload: RecetaUpdateRequest,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    rec = db.query(Receta).filter(Receta.idReceta == receta_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Receta no encontrada")
    assert_same_empresa(auth, int(rec.empresaID))

    producto_id = payload.productoID
    producto_nuevo_sucursal_id: int | None = None
    if producto_id is not None:
        existe = db.execute(
            text("SELECT 1 FROM petalops.producto WHERE id_producto = :id AND empresa_id = :empresa_id"),
            {"id": int(producto_id), "empresa_id": int(rec.empresaID)},
        ).first()
        if not existe:
            raise HTTPException(status_code=400, detail="Producto no válido para esta empresa")
        rec.productoID = producto_id
    elif payload.precioVenta is not None:
        rec.productoID = _crear_producto_para_receta(
            db,
            empresa_id=int(rec.empresaID),
            sucursal_id=auth.sucursalID,
            nombre=payload.nombre,
            descripcion=payload.descripcion,
            precio=payload.precioVenta,
            imagen_url=payload.imagenUrl,
        )
        producto_nuevo_sucursal_id = auth.sucursalID

    rec.nombre = payload.nombre.strip()
    rec.descripcion = (payload.descripcion.strip() if payload.descripcion else None)
    rec.capacidadManual = payload.capacidadManual
    rec.activo = bool(payload.activo)
    rec.updatedAt = datetime.now(timezone.utc)

    try:
        db.commit()
        db.refresh(rec)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=400, detail="No fue posible actualizar receta")

    # Producto recien creado y comiteado: invalidar catalogo cacheado para que aparezca sin esperar el TTL.
    _invalidate_catalogo_cache(int(rec.empresaID), producto_nuevo_sucursal_id)

    return obtener_receta(receta_id, db=db, auth=auth)


@router.post("/recetas/{receta_id}/ingredientes", response_model=RecetaItem, dependencies=[Depends(require_module_access("inventario", "puedeEditar"))])
def agregar_ingrediente_receta(
    receta_id: int,
    payload: RecetaDetalleAgregarRequest,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    rec = db.query(Receta).filter(Receta.idReceta == receta_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Receta no encontrada")
    assert_same_empresa(auth, int(rec.empresaID))

    # Verify inventario belongs to same empresa
    inv = db.query(Inventario).filter(
        Inventario.idInventario == int(payload.inventarioID),
        Inventario.empresaID == int(rec.empresaID),
    ).first()
    if not inv:
        raise HTTPException(status_code=400, detail="Item de inventario no válido para esta empresa")

    now = datetime.now(timezone.utc)
    try:
        det = RecetaDetalle(
            empresaID=int(rec.empresaID),
            recetaID=receta_id,
            inventarioID=int(payload.inventarioID),
            cantidad=Decimal(payload.cantidad),
            createdAt=now,
        )
        db.add(det)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=400, detail="No fue posible agregar ingrediente (ya existe o datos inválidos)")

    return obtener_receta(receta_id, db=db, auth=auth)


@router.put("/recetas/{receta_id}/ingredientes/{detalle_id}", response_model=RecetaItem, dependencies=[Depends(require_module_access("inventario", "puedeEditar"))])
def actualizar_ingrediente_receta(
    receta_id: int,
    detalle_id: int,
    payload: RecetaDetalleActualizarRequest,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    rec = db.query(Receta).filter(Receta.idReceta == receta_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Receta no encontrada")
    assert_same_empresa(auth, int(rec.empresaID))

    det = db.query(RecetaDetalle).filter(
        RecetaDetalle.idRecetaDetalle == detalle_id,
        RecetaDetalle.recetaID == receta_id,
    ).first()
    if not det:
        raise HTTPException(status_code=404, detail="Ingrediente no encontrado")

    det.cantidad = Decimal(payload.cantidad)
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=400, detail="No fue posible actualizar cantidad")

    return obtener_receta(receta_id, db=db, auth=auth)


@router.delete("/recetas/{receta_id}/ingredientes/{detalle_id}", response_model=RecetaItem, dependencies=[Depends(require_module_access("inventario", "puedeEditar"))])
def eliminar_ingrediente_receta(
    receta_id: int,
    detalle_id: int,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    rec = db.query(Receta).filter(Receta.idReceta == receta_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Receta no encontrada")
    assert_same_empresa(auth, int(rec.empresaID))

    det = db.query(RecetaDetalle).filter(
        RecetaDetalle.idRecetaDetalle == detalle_id,
        RecetaDetalle.recetaID == receta_id,
    ).first()
    if not det:
        raise HTTPException(status_code=404, detail="Ingrediente no encontrado")

    db.delete(det)
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=400, detail="No fue posible eliminar ingrediente")

    return obtener_receta(receta_id, db=db, auth=auth)


@router.delete("/recetas/{receta_id}", dependencies=[Depends(require_module_access("inventario", "puedeEliminar"))])
def eliminar_receta(
    receta_id: int,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    rec = db.query(Receta).filter(Receta.idReceta == receta_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Receta no encontrada")
    assert_same_empresa(auth, int(rec.empresaID))

    db.delete(rec)
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=400, detail="No fue posible eliminar receta")

    return {"status": "ok"}
