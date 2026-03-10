from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.security import assert_same_empresa, get_current_auth_context, require_module_access
from app.database import get_db
from app.models.inventario import Inventario
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


def _status_stock(activo: bool, stock_actual: Decimal, stock_minimo: Decimal) -> str:
    if not bool(activo):
        return "Inactivo"
    if Decimal(stock_actual or 0) == Decimal("0"):
        return "Agotado"
    if Decimal(stock_actual or 0) <= Decimal(stock_minimo or 0):
        return "Bajo Stock"
    return "Disponible"


def _to_item(row: Inventario, proveedor_nombre: str | None = None) -> InventarioItem:
    stock_actual = Decimal(row.stockActual or 0)
    stock_minimo = Decimal(row.stockMinimo or 0)
    return InventarioItem(
        inventarioID=int(row.idInventario),
        empresaID=int(row.empresaID),
        codigo=str(row.codigo or ""),
        nombre=str(row.nombre or ""),
        categoria=str(row.categoria or ""),
        subcategoria=(str(row.subcategoria) if row.subcategoria is not None else None),
        color=(str(row.color) if row.color is not None else None),
        descripcion=(str(row.descripcion) if row.descripcion is not None else None),
        proveedorID=(int(row.proveedorID) if row.proveedorID is not None else None),
        proveedor=proveedor_nombre,
        codigoProveedor=(str(row.codigoProveedor) if row.codigoProveedor is not None else None),
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


@router.get("/proveedores", response_model=ProveedorListResponse)
def listar_proveedores(
    empresa_id: int = Query(..., alias="empresaID"),
    q: str | None = Query(None),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)

    query = db.query(Proveedor).filter(Proveedor.empresaID == empresa_id)
    if q:
        term = f"%{q.strip()}%"
        query = query.filter(
            Proveedor.nombreProveedor.like(term)
            | Proveedor.codigoProveedor.like(term)
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
    proveedor = Proveedor(
        empresaID=int(empresa_id),
        nombreProveedor=payload.nombre.strip(),
        codigoProveedor=(payload.codigoProveedor.strip() if payload.codigoProveedor else None),
        activo=bool(payload.activo),
        createdAt=now,
        updatedAt=now,
    )
    db.add(proveedor)
    try:
        db.commit()
        db.refresh(proveedor)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=400, detail="No fue posible crear proveedor (codigo duplicado o datos invalidos)")

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
        db.query(Inventario, Proveedor)
        .outerjoin(Proveedor, Proveedor.idProveedor == Inventario.proveedorID)
        .filter(Inventario.empresaID == empresa_id)
    )

    if categoria:
        query = query.filter(func.upper(Inventario.categoria) == categoria.strip().upper())

    if proveedor_id is not None:
        query = query.filter(Inventario.proveedorID == int(proveedor_id))

    if q:
        term = f"%{q.strip()}%"
        query = query.filter(
            Inventario.codigo.like(term)
            | Inventario.nombre.like(term)
            | Inventario.subcategoria.like(term)
            | Inventario.color.like(term)
            | Inventario.descripcion.like(term)
            | Inventario.codigoProveedor.like(term)
            | Proveedor.nombreProveedor.like(term)
        )

    rows = query.order_by(Inventario.categoria.asc(), Inventario.nombre.asc()).all()
    items = [_to_item(item, (str(proveedor.nombreProveedor) if proveedor else None)) for item, proveedor in rows]

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
        proveedor = db.query(Proveedor).filter(
            Proveedor.idProveedor == int(payload.proveedorID),
            Proveedor.empresaID == int(payload.empresaID),
        ).first()
        if not proveedor:
            raise HTTPException(status_code=400, detail="Proveedor no valido para la empresa")

    now = datetime.now(timezone.utc)
    item = Inventario(
        empresaID=int(payload.empresaID),
        codigo=payload.codigo.strip(),
        nombre=payload.nombre.strip(),
        categoria=payload.categoria.strip(),
        subcategoria=(payload.subcategoria.strip() if payload.subcategoria else None),
        color=(payload.color.strip() if payload.color else None),
        descripcion=(payload.descripcion.strip() if payload.descripcion else None),
        proveedorID=(int(payload.proveedorID) if payload.proveedorID is not None else None),
        codigoProveedor=(payload.codigoProveedor.strip() if payload.codigoProveedor else None),
        stockActual=payload.stockActual,
        stockMinimo=payload.stockMinimo,
        valorUnitario=payload.valorUnitario,
        activo=bool(payload.activo),
        fechaUltimaActualizacion=now,
        createdAt=now,
        updatedAt=now,
    )

    db.add(item)
    try:
        db.flush()

        if Decimal(payload.stockActual) > 0:
            mov = MovimientoInventario(
                empresaID=int(payload.empresaID),
                inventarioID=int(item.idInventario),
                tipoMovimiento="Entrada",
                cantidad=Decimal(payload.stockActual),
                fecha=now,
                motivo="Carga inicial",
                usuarioID=int(auth.userID),
                createdAt=now,
            )
            db.add(mov)

        db.commit()
        db.refresh(item)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=400, detail="No fue posible crear item de inventario (codigo duplicado o datos invalidos)")

    proveedor_nombre = None
    if item.proveedorID is not None:
        proveedor = db.query(Proveedor).filter(Proveedor.idProveedor == item.proveedorID).first()
        proveedor_nombre = str(proveedor.nombreProveedor) if proveedor else None

    return InventarioMutationResponse(status="ok", item=_to_item(item, proveedor_nombre))


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

    if payload.proveedorID is not None:
        proveedor = db.query(Proveedor).filter(
            Proveedor.idProveedor == int(payload.proveedorID),
            Proveedor.empresaID == int(item.empresaID),
        ).first()
        if not proveedor:
            raise HTTPException(status_code=400, detail="Proveedor no valido para la empresa")

    now = datetime.now(timezone.utc)
    item.nombre = payload.nombre.strip()
    item.categoria = payload.categoria.strip()
    item.subcategoria = (payload.subcategoria.strip() if payload.subcategoria else None)
    item.color = (payload.color.strip() if payload.color else None)
    item.descripcion = (payload.descripcion.strip() if payload.descripcion else None)
    item.proveedorID = (int(payload.proveedorID) if payload.proveedorID is not None else None)
    item.codigoProveedor = (payload.codigoProveedor.strip() if payload.codigoProveedor else None)
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

    proveedor_nombre = None
    if item.proveedorID is not None:
        proveedor = db.query(Proveedor).filter(Proveedor.idProveedor == item.proveedorID).first()
        proveedor_nombre = str(proveedor.nombreProveedor) if proveedor else None

    return InventarioMutationResponse(status="ok", item=_to_item(item, proveedor_nombre))


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
        tipoMovimiento=movimiento_tipo,
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

    proveedor_nombre = None
    if item.proveedorID is not None:
        proveedor = db.query(Proveedor).filter(Proveedor.idProveedor == item.proveedorID).first()
        proveedor_nombre = str(proveedor.nombreProveedor) if proveedor else None

    return InventarioMutationResponse(status="ok", item=_to_item(item, proveedor_nombre))


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

    try:
        db.commit()
        db.refresh(item)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=400, detail="No fue posible actualizar estado del item")

    proveedor_nombre = None
    if item.proveedorID is not None:
        proveedor = db.query(Proveedor).filter(Proveedor.idProveedor == item.proveedorID).first()
        proveedor_nombre = str(proveedor.nombreProveedor) if proveedor else None

    return InventarioMutationResponse(status="ok", item=_to_item(item, proveedor_nombre))


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
        db.query(MovimientoInventario, Inventario)
        .join(Inventario, Inventario.idInventario == MovimientoInventario.inventarioID)
        .filter(MovimientoInventario.empresaID == empresa_id)
    )

    if inventario_id is not None:
        query = query.filter(MovimientoInventario.inventarioID == inventario_id)

    if tipo:
        tipo_norm = _normalize_movimiento_tipo(tipo)
        query = query.filter(func.upper(MovimientoInventario.tipoMovimiento) == tipo_norm.upper())

    if q:
        term = f"%{q.strip()}%"
        query = query.filter(
            Inventario.codigo.like(term)
            | Inventario.nombre.like(term)
            | MovimientoInventario.motivo.like(term)
        )

    rows = query.order_by(MovimientoInventario.fecha.desc(), MovimientoInventario.idMovimiento.desc()).all()

    items = [
        MovimientoInventarioItem(
            movimientoID=int(mov.idMovimiento),
            inventarioID=int(mov.inventarioID),
            codigo=str(inv.codigo or ""),
            nombre=str(inv.nombre or ""),
            tipoMovimiento=str(mov.tipoMovimiento or ""),
            cantidad=Decimal(mov.cantidad or 0),
            fecha=mov.fecha,
            motivo=(str(mov.motivo) if mov.motivo is not None else None),
            usuarioID=(int(mov.usuarioID) if mov.usuarioID is not None else None),
        )
        for mov, inv in rows
    ]
    return MovimientoInventarioListResponse(items=items, total=len(items))
