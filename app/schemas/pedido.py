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
    tipoIdent: Optional[str] = None
    identificacion: Optional[str] = None
    indicativo: Optional[str] = None
    nombreCompleto: str
    telefono: str
    email: Optional[str] = None


class CheckoutEntregaInput(BaseModel):
    tipoEntrega: Optional[str] = None
    destinatario: Optional[str] = None
    telefonoDestino: Optional[str] = None
    direccion: str
    barrioID: Optional[int] = None
    barrioNombre: Optional[str] = None
    fechaEntrega: datetime
    rangoHora: Optional[str] = None
    mensaje: Optional[str] = None
    firma: Optional[str] = None
    observacionGeneral: Optional[str] = None


class PedidoCheckoutRequest(BaseModel):
    empresaID: int
    sucursalID: int
    productos: List[CheckoutProductoItem]
    cliente: CheckoutClienteInput
    entrega: CheckoutEntregaInput


class PedidoCheckoutResponse(BaseModel):
    pedidoID: int
    numeroPedido: int
    codigoPedido: str
    total: float
    estado: str


class PedidoListItem(BaseModel):
    pedidoID: int
    numeroPedido: int
    codigoPedido: Optional[str] = None
    empresaID: int
    sucursalID: int
    fecha: Optional[datetime] = None
    fechaPedido: Optional[str] = None
    horaPedido: Optional[str] = None
    cliente: str
    destinatario: Optional[str] = None
    fechaEntrega: Optional[datetime] = None
    horaEntrega: Optional[str] = None
    productos: List[str]
    total: float
    metodoPago: Optional[str] = None
    estado: str
    telefono: Optional[str] = None
    telefonoCompleto: Optional[str] = None


class PedidoListResponse(BaseModel):
    items: List[PedidoListItem]
    total: int
    page: int
    pageSize: int


class PedidoDetalleProducto(BaseModel):
    productoID: int
    nombreProducto: str
    cantidad: float
    precioUnitario: float
    subtotal: float


class PedidoDetalleResponse(BaseModel):
    pedidoID: int
    numeroPedido: int
    codigoPedido: Optional[str] = None
    fecha: Optional[datetime] = None
    fechaPedido: Optional[str] = None
    horaPedido: Optional[str] = None
    estado: str
    empresaID: int
    sucursalID: int
    motivoRechazo: Optional[str] = None
    cliente: dict
    destinatario: dict
    financiero: dict
    productos: List[PedidoDetalleProducto]


class RechazarPedidoRequest(BaseModel):
    motivo: str