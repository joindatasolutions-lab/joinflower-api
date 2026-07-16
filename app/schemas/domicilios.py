from datetime import date, datetime

from pydantic import BaseModel, Field


ESTADO_PENDIENTE = "Pendiente"
ESTADO_ASIGNADO = "Asignado"
ESTADO_EN_RUTA = "EnRuta"
ESTADO_ENTREGADO = "Entregado"
ESTADO_NO_ENTREGADO = "NoEntregado"
ESTADO_CANCELADO = "Cancelado"


class DomiciliarioItem(BaseModel):
    idDomiciliario: int
    usuarioID: int | None = None
    nombre: str
    telefono: str | None = None
    activo: bool


class DomiciliarioListResponse(BaseModel):
    items: list[DomiciliarioItem]


class DomicilioAdminItem(BaseModel):
    idEntrega: int
    produccionID: int | None = None
    pedidoID: int
    numeroPedido: str
    codigoPedido: str | None = None
    cliente: str
    destinatario: str | None = None
    telefonoDestino: str | None = None
    direccion: str | None = None
    barrioId: int | None = None
    nombreBarrio: str | None = None
    barrio: str | None = None
    zonaId: int | None = None
    nombreZona: str | None = None
    zona: str | None = None
    observacion: str | None = None
    horaEntrega: str | None = None
    fechaEntregaProgramada: datetime | None = None
    domiciliarioID: int | None = None
    domiciliario: str | None = None
    estado: str
    intentoNumero: int
    tiempoRestanteHoras: int | None = None
    prioridad: str | None = None
    latitudDestino: float | None = None
    longitudDestino: float | None = None
    latitudEntrega: float | None = None
    longitudEntrega: float | None = None


class DomicilioAdminListResponse(BaseModel):
    items: list[DomicilioAdminItem]
    total: int


class DomicilioCourierCard(BaseModel):
    idEntrega: int
    pedidoID: int
    numeroPedido: str
    codigoPedido: str | None = None
    cliente: str | None = None
    destinatario: str | None = None
    direccion: str | None = None
    barrioId: int | None = None
    nombreBarrio: str | None = None
    barrio: str | None = None
    zonaId: int | None = None
    nombreZona: str | None = None
    zona: str | None = None
    telefonoDestino: str | None = None
    mensaje: str | None = None
    observacion: str | None = None
    estado: str
    horaEntrega: str | None = None
    fechaEntregaProgramada: datetime | None = None
    prioridad: str | None = None
    latitudDestino: float | None = None
    longitudDestino: float | None = None
    latitudEntrega: float | None = None
    longitudEntrega: float | None = None
    distanciaKm: float | None = None


class DomicilioCourierListResponse(BaseModel):
    items: list[DomicilioCourierCard]
    total: int


class DomicilioContadoresResponse(BaseModel):
    asignados: int
    enCamino: int
    entregados: int
    disponibles: int


class PedidoDisponibleItem(BaseModel):
    id: int
    numeroPedido: str
    cliente: str
    direccion: str | None = None
    horaEntrega: str | None = None
    fechaEntregaProgramada: datetime | None = None
    barrioId: int | None = None
    nombreBarrio: str | None = None
    barrio: str | None = None
    zonaId: int | None = None
    nombreZona: str | None = None
    zona: str | None = None
    estado: str
    prioridad: str | None = None


class PedidoAsignadoResponse(PedidoDisponibleItem):
    idEntrega: int
    domiciliarioID: int
    fechaAsignacion: datetime
    contadores: DomicilioContadoresResponse | None = None


class AsignarDomiciliarioRequest(BaseModel):
    domiciliarioID: int | None = None
    usuarioCambio: str = Field(min_length=2)


class MarcarEnRutaRequest(BaseModel):
    usuarioCambio: str = Field(min_length=2)


class TomarEntregaRequest(BaseModel):
    usuarioCambio: str = Field(min_length=2)


class MarcarEntregadoRequest(BaseModel):
    usuarioCambio: str = Field(min_length=2)
    firmaNombre: str = Field(min_length=2)
    firmaDocumento: str = Field(min_length=4)
    firmaImagenUrl: str = Field(min_length=8)
    evidenciaFotoUrl: str | None = None
    latitudEntrega: float
    longitudEntrega: float
    observaciones: str | None = None


class MarcarNoEntregadoRequest(BaseModel):
    usuarioCambio: str = Field(min_length=2)
    motivo: str = Field(min_length=4)
    reprogramarPara: datetime | None = None
    observaciones: str | None = None


class DomicilioActionResponse(BaseModel):
    status: str
    idEntrega: int
    estado: str


class FiltroEstadoResponse(BaseModel):
    filtro: str
    fecha: date


class OrderItemDetail(BaseModel):
    """Detalle de un item del pedido con información del producto"""
    productId: int
    name: str
    qty: int
    imageUrl: str | None = None


class DomicilioDetailResponse(BaseModel):
    """Respuesta GET /domicilios/:id con detalles del pedido"""
    idEntrega: int
    numeroPedido: str
    cliente: str
    items: list[OrderItemDetail]
    customerMessage: str | None = None  # Solo para usuarios autorizados
