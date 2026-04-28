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
    normalized = str(value or "").strip().lower()
    mapping = {
        "entrada": "Entrada",
        "salida": "Salida",
        "ajuste": "Ajuste",
    }
    if normalized not in mapping:
        raise HTTPException(status_code=400, detail="tipoMovimiento debe ser Entrada, Salida o Ajuste")
    return mapping[normalized]


MOVIMIENTO_TIPO_CODIGO_A_ID = {
    "entrada": 1,
    "salida": 2,
    "ajuste": 3,
}

MOVIMIENTO_TIPO_ID_A_LABEL = {
    1: "Entrada",
    2: "Salida",
    3: "Ajuste",
}


def _resolve_movimiento_tipo_id(db: Session, value: str) -> int:
    tipo = _normalize_movimiento_tipo(value)
    codigo = tipo.lower()
    row = db.execute(
        text(
            """
            SELECT id_tipo_movimiento
            FROM petalops.tipo_movimiento
            WHERE lower(codigo) = :codigo
               OR lower(nombre) = :codigo
            LIMIT 1
            """
        ),
        {"codigo": codigo},
    ).first()
    if row:
        return int(row[0])
    resolved = MOVIMIENTO_TIPO_CODIGO_A_ID.get(codigo)
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
    return _to_item(
        item,
        codigo=(str(insumo.codigoBarra) if insumo and insumo.codigoBarra else None),
        nombre=(str(insumo.nombreInsumo) if insumo and insumo.nombreInsumo else None),
        categoria=(str(insumo.unidadMedida) if insumo and insumo.unidadMedida else "Insumos"),
        proveedor_id=(int(insumo.proveedorID) if insumo and insumo.proveedorID is not None else None),
        proveedor_nombre=(str(proveedor.nombreProveedor) if proveedor else None),
        codigo_proveedor=(str(proveedor.codigoProveedor) if proveedor and proveedor.codigoProveedor is not None else None),
    )


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


@router.get("", response_model=InventarioListResponse)
def listar_inventario(
    empresa_id: int = Query(..., alias="empresaID"),
    categoria: str | None = Query(None),
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

    if categoria:
        query = query.filter(func.upper(Insumo.unidadMedida) == categoria.strip().upper())

    if proveedor_id is not None:
        query = query.filter(Proveedor.idProveedor == int(proveedor_id))

    if q:
        term = f"%{q.strip()}%"
        query = query.filter(
            func.cast(Inventario.idInventario, String).ilike(term)
            | func.cast(Inventario.insumoID, String).ilike(term)
            | Insumo.nombreInsumo.ilike(term)
            | Insumo.codigoBarra.ilike(term)
            | Insumo.unidadMedida.ilike(term)
            | Proveedor.codigoProveedor.ilike(term)
            | Proveedor.nombreProveedor.ilike(term)
        )

    rows = query.order_by(Insumo.unidadMedida.asc(), Insumo.nombreInsumo.asc()).all()
    items = [
        _to_item(
            item,
            codigo=(str(insumo.codigoBarra) if insumo and insumo.codigoBarra else None),
            nombre=(str(insumo.nombreInsumo) if insumo and insumo.nombreInsumo else None),
            categoria=(str(insumo.unidadMedida) if insumo and insumo.unidadMedida else "Insumos"),
            proveedor_id=(int(proveedor.idProveedor) if proveedor else None),
            proveedor_nombre=(str(proveedor.nombreProveedor) if proveedor else None),
            codigo_proveedor=(str(proveedor.codigoProveedor) if proveedor and proveedor.codigoProveedor is not None else None),
        )
        for item, insumo, proveedor in rows
    ]

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

    now = datetime.now(timezone.utc)
    try:
        insumo_row = db.execute(
            text(
                """
                INSERT INTO petalops.insumo (
                    empresa_id,
                    codigo_barra,
                    nombre_insumo,
                    unidad_medida,
                    activo,
                    created_at,
                    updated_at,
                    proveedor_id
                ) VALUES (
                    :empresa_id,
                    :codigo_barra,
                    :nombre_insumo,
                    :unidad_medida,
                    :activo,
                    :created_at,
                    :updated_at,
                    :proveedor_id
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
                    empresa_id,
                    sucursal_id,
                    insumo_id,
                    stock_actual,
                    stock_reservado,
                    stock_minimo,
                    valor_unitario,
                    activo,
                    fechaultimaactualizacion,
                    created_at,
                    updated_at
                ) VALUES (
                    :empresa_id,
                    :sucursal_id,
                    :insumo_id,
                    :stock_actual,
                    :stock_reservado,
                    :stock_minimo,
                    :valor_unitario,
                    :activo,
                    :fecha_actualizacion,
                    :created_at,
                    :updated_at
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
                        empresa_id,
                        inventario_id,
                        tipo_movimiento_id,
                        cantidad,
                        fecha,
                        motivo,
                        usuario_id,
                        created_at
                    ) VALUES (
                        :empresa_id,
                        :inventario_id,
                        :tipo_movimiento_id,
                        :cantidad,
                        :fecha,
                        :motivo,
                        :usuario_id,
                        :created_at
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

    now = datetime.now(timezone.utc)
    insumo.nombreInsumo = payload.nombre.strip()
    insumo.unidadMedida = payload.categoria.strip()
    insumo.proveedorID = (int(payload.proveedorID) if payload.proveedorID is not None else None)
    insumo.updatedAt = now
    insumo.activo = bool(item.activo)
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
    elif movimiento_tipo == "Salida":
        if cantidad <= 0:
            raise HTTPException(status_code=400, detail="cantidad debe ser mayor a 0 para Salida")
        nuevo_stock = stock_actual - cantidad
        if nuevo_stock < 0:
            raise HTTPException(status_code=400, detail="No se permite stock negativo")
        cantidad_mov = cantidad
    else:
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
