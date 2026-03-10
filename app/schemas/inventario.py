from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class ProveedorCreateRequest(BaseModel):
    nombre: str = Field(min_length=2, max_length=150)
    codigoProveedor: str | None = Field(default=None, max_length=80)
    activo: bool = True


class ProveedorItem(BaseModel):
    idProveedor: int
    nombre: str
    codigoProveedor: str | None = None
    activo: bool


class ProveedorListResponse(BaseModel):
    items: list[ProveedorItem]
    total: int


class InventarioCreateRequest(BaseModel):
    empresaID: int
    codigo: str = Field(min_length=1, max_length=80)
    nombre: str = Field(min_length=2, max_length=180)
    categoria: str = Field(min_length=2, max_length=80)
    subcategoria: str | None = Field(default=None, max_length=80)
    color: str | None = Field(default=None, max_length=80)
    descripcion: str | None = Field(default=None, max_length=255)
    proveedorID: int | None = None
    codigoProveedor: str | None = Field(default=None, max_length=80)
    stockActual: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    stockMinimo: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    valorUnitario: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    activo: bool = True


class InventarioUpdateRequest(BaseModel):
    nombre: str = Field(min_length=2, max_length=180)
    categoria: str = Field(min_length=2, max_length=80)
    subcategoria: str | None = Field(default=None, max_length=80)
    color: str | None = Field(default=None, max_length=80)
    descripcion: str | None = Field(default=None, max_length=255)
    proveedorID: int | None = None
    codigoProveedor: str | None = Field(default=None, max_length=80)
    stockMinimo: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    valorUnitario: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))


class InventarioStockAdjustRequest(BaseModel):
    tipoMovimiento: str = Field(min_length=3, max_length=20)
    cantidad: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    stockObjetivo: Decimal | None = Field(default=None, ge=Decimal("0"))
    motivo: str = Field(min_length=3, max_length=250)


class InventarioActivoRequest(BaseModel):
    activo: bool


class InventarioItem(BaseModel):
    inventarioID: int
    empresaID: int
    codigo: str
    nombre: str
    categoria: str
    subcategoria: str | None = None
    color: str | None = None
    descripcion: str | None = None
    proveedorID: int | None = None
    proveedor: str | None = None
    codigoProveedor: str | None = None
    stockActual: Decimal
    stockMinimo: Decimal
    valorUnitario: Decimal
    activo: bool
    estadoStock: str
    fechaUltimaActualizacion: datetime | None = None


class InventarioListResponse(BaseModel):
    items: list[InventarioItem]
    total: int


class InventarioMutationResponse(BaseModel):
    status: str
    item: InventarioItem


class MovimientoInventarioItem(BaseModel):
    movimientoID: int
    inventarioID: int
    codigo: str
    nombre: str
    tipoMovimiento: str
    cantidad: Decimal
    fecha: datetime
    motivo: str | None = None
    usuarioID: int | None = None


class MovimientoInventarioListResponse(BaseModel):
    items: list[MovimientoInventarioItem]
    total: int
