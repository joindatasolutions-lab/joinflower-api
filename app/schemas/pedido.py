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
    latitudDestino: Optional[float] = None
    longitudDestino: Optional[float] = None
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
    latitudDestino: Optional[float] = None
    longitudDestino: Optional[float] = None
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


class PedidoManualProductoItem(BaseModel):
    productoID: Optional[int] = None
    productoId: Optional[int] = None
    cantidad: float = 1
    productoPrecio: Optional[float] = None
    precioUnitario: Optional[float] = None
    productoObservaciones: Optional[str] = None
    observaciones: Optional[str] = None


class PedidoManualClienteInput(BaseModel):
    clienteID: Optional[int] = None
    clienteId: Optional[int] = None
    tipoIdent: Optional[str] = None
    identificacion: Optional[str] = None
    indicativo: Optional[str] = None
    nombreCompleto: Optional[str] = None
    nombres: Optional[str] = None
    telefono: Optional[str] = None
    email: Optional[str] = None


class PedidoManualEntregaInput(BaseModel):
    tipoEntrega: Optional[str] = None
    destinatario: Optional[str] = None
    destinatarioNombre: Optional[str] = None
    telefonoDestino: Optional[str] = None
    direccion: str
    barrioID: Optional[int] = None
    barrioId: Optional[int] = None
    barrioNombre: Optional[str] = None
    latitudDestino: Optional[float] = None
    longitudDestino: Optional[float] = None
    fechaEntrega: Optional[datetime | str] = None
    horaEntrega: Optional[str] = None
    rangoHora: Optional[str] = None
    mensaje: Optional[str] = None
    mensajeTarjeta: Optional[str] = None
    firma: Optional[str] = None
    observacionGeneral: Optional[str] = None


class PedidoManualRequest(BaseModel):
    empresaID: Optional[int] = None
    empresaId: Optional[int] = None
    sucursalID: Optional[int] = None
    sucursalId: Optional[int] = None
    productos: Optional[List[PedidoManualProductoItem]] = None
    items: Optional[List[PedidoManualProductoItem]] = None
    cliente: PedidoManualClienteInput
    entrega: PedidoManualEntregaInput
    domicilio: Optional[float] = None
    domicilioOriginal: Optional[float] = None
    descuentoDomicilio: Optional[float] = None
    domicilioObsequiado: bool = False
    omitirCostoDomicilio: bool = False


class PedidoCheckoutResponse(BaseModel):
    pedidoID: int
    numeroPedido: Optional[int] = None
    codigoPedido: Optional[str] = None
    pedidoIDs: Optional[List[int]] = None
    cantidadPedidos: Optional[int] = None
    total: float
    estado: str


class PedidoManualResponse(PedidoCheckoutResponse):
    domicilioObsequiado: Optional[bool] = None
    omitirCostoDomicilio: Optional[bool] = None
    domicilio: Optional[float] = None
    domicilioOriginal: Optional[float] = None
    descuentoDomicilio: Optional[float] = None


class PedidoListProducto(BaseModel):
    productoID: int
    codigoProducto: Optional[str] = None
    codigoCatalogo: Optional[str] = None
    nombreProducto: str
    cantidad: float


class PedidoListItem(BaseModel):
    pedidoID: int
    numeroPedido: Optional[int] = None
    codigoPedido: Optional[str] = None
    empresaID: int
    sucursalID: int
    fecha: Optional[datetime] = None
    fechaPedido: Optional[str] = None
    horaPedido: Optional[str] = None
    cliente: str
    destinatario: Optional[str] = None
    tipoEntrega: Optional[str] = None
    direccionEntrega: Optional[str] = None
    barrioNombre: Optional[str] = None
    fechaEntrega: Optional[datetime] = None
    horaEntrega: Optional[str] = None
    productos: List[str]
    productosDetalle: Optional[List[PedidoListProducto]] = None
    total: float
    metodoPago: Optional[str] = None
    canalFlora: Optional[str] = None
    puedeAprobar: Optional[bool] = None
    motivoBloqueoAprobacion: Optional[str] = None
    estado: str
    motivoRechazo: Optional[str] = None
    telefono: Optional[str] = None
    telefonoCompleto: Optional[str] = None
    facturaImpresa: Optional[bool] = None
    facturaImpresaAt: Optional[str] = None


class PedidoListKpiSummary(BaseModel):
    ventaHoy: float = 0
    pedidosHoy: int = 0
    aprobados: int = 0
    pendientes: int = 0
    cancelados: int = 0
    sinImprimir: int = 0


class PedidoListResponse(BaseModel):
    items: List[PedidoListItem]
    total: int
    page: int
    pageSize: int
    facturasPendientesImpresion: Optional[int] = None
    kpis: Optional[PedidoListKpiSummary] = None


class PedidoDetalleProducto(BaseModel):
    detalleID: Optional[int] = None
    productoID: int
    codigoProducto: Optional[str] = None
    codigoCatalogo: Optional[str] = None
    nombreProducto: str
    cantidad: float
    observaciones: Optional[str] = None
    notasProduccion: Optional[str] = None
    observacionesPersonalizadas: Optional[str] = None
    precioUnitario: float
    subtotal: float


class PedidoDetalleResponse(BaseModel):
    pedidoID: int
    numeroPedido: Optional[int] = None
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
    camposEmpresa: Optional[dict] = None
    productos: List[PedidoDetalleProducto]


class RechazarPedidoRequest(BaseModel):
    motivo: str
