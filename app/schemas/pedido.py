from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


class PedidoItem(BaseModel):
    productoId: int
    cantidad: int


class ClienteInput(BaseModel):
    nombres: str
    telefono: str
    email: Optional[str] = None


class EntregaInput(BaseModel):
    tipoEntrega: str
    direccion: str
    barrioId: Optional[int] = None
    destinatarioNombre: str
    mensaje: Optional[str] = None


class PedidoCreate(BaseModel):
    empresaId: int
    sucursalId: int
    cliente: ClienteInput
    entrega: EntregaInput
    items: List[PedidoItem]


class CheckoutProductoItem(BaseModel):
    productoID: int
    cantidad: int


class CheckoutClienteInput(BaseModel):
    nombreCompleto: str
    telefono: str
    email: Optional[str] = None


class CheckoutEntregaInput(BaseModel):
    direccion: str
    barrioID: Optional[int] = None
    fechaEntrega: datetime
    mensaje: Optional[str] = None


class PedidoCheckoutRequest(BaseModel):
    empresaID: int
    sucursalID: int
    productos: List[CheckoutProductoItem]
    cliente: CheckoutClienteInput
    entrega: CheckoutEntregaInput


class PedidoCheckoutResponse(BaseModel):
    pedidoID: int
    total: float
    estado: str