import re
import secrets
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
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
from app.schemas.inventario import (
    InventarioActivoRequest,
    InventarioCreateRequest,
    InventarioItem,
    InventarioListResponse,
    InventarioMutationResponse,
    InventarioStockAdjustRequest,
    InventarioUpdateRequest,
    MovimientoInventarioItem,
    MovimientoInventarioListResponse,
    ProveedorCreateRequest,
    ProveedorItem,
    ProveedorListResponse,
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
                    activo,
                    created_at,
                    updated_at
                )
                VALUES (
                    :empresa_id,
                    :nombre,
                    :codigo_proveedor,
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
        activo=bool(proveedor.activo),
    )


# ---------------------------------------------------------------------------
# Inventario
# ---------------------------------------------------------------------------

@router.get("", response_model=InventarioListResponse)
def listar_inventario(
    empresa_id: int = Query(..., alias="empresaID"),
    categoria: str | None = Query(None),
    subcategoria: str | None = Query(None),
    estado: str | None = Query(None),
    proveedor_id: int | None = Query(None, alias="proveedorID"),
    q: str | None = Query(None),
    solo_criticos: bool = Query(False, alias="soloCriticos"),
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

    return InventarioListResponse(items=items, total=len(items))


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
    )
    db.add(movimiento)

    try:
        db.commit()
        db.refresh(item)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=400, detail="No fue posible ajustar stock")

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

    if inventario_id is not None:
        query = query.filter(MovimientoInventario.inventarioID == inventario_id)

    if tipo:
        tipo_id = _resolve_movimiento_tipo_id(db, tipo)
        query = query.filter(MovimientoInventario.tipoMovimiento == tipo_id)

    if q:
        term = f"%{q.strip()}%"
        query = query.filter(
            Insumo.nombreInsumo.ilike(term)
            | Insumo.codigoBarra.ilike(term)
            | MovimientoInventario.motivo.ilike(term)
        )

    rows = query.order_by(MovimientoInventario.fecha.desc(), MovimientoInventario.idMovimiento.desc()).all()

    items = [
        MovimientoInventarioItem(
            movimientoID=int(mov.idMovimiento),
            inventarioID=int(mov.inventarioID),
            codigo=(str(ins.codigoBarra) if ins and ins.codigoBarra else f"INS-{int(inv.insumoID)}"),
            nombre=(str(ins.nombreInsumo) if ins and ins.nombreInsumo else f"Insumo {int(inv.insumoID)}"),
            tipoMovimiento=_movimiento_tipo_label(mov.tipoMovimiento),
            cantidad=Decimal(mov.cantidad or 0),
            fecha=mov.fecha,
            motivo=(str(mov.motivo) if mov.motivo is not None else None),
            usuarioID=(int(mov.usuarioID) if mov.usuarioID is not None else None),
        )
        for mov, inv, ins in rows
    ]
    return MovimientoInventarioListResponse(items=items, total=len(items))


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
