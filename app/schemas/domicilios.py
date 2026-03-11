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
    nombre: str
    telefono: str | None = None
    activo: bool


class DomiciliarioListResponse(BaseModel):
    items: list[DomiciliarioItem]


class DomicilioAdminItem(BaseModel):
    idEntrega: int
    produccionID: int | None = None
    pedidoID: int
    numeroPedido: int
    codigoPedido: str | None = None
    cliente: str
    destinatario: str | None = None
    telefonoDestino: str | None = None
    direccion: str | None = None
    barrio: str | None = None
    horaEntrega: str | None = None
    fechaEntregaProgramada: datetime | None = None
    domiciliarioID: int | None = None
    domiciliario: str | None = None
    estado: str
    intentoNumero: int
    tiempoRestanteHoras: int | None = None
    prioridad: str | None = None
    latitudEntrega: float | None = None
    longitudEntrega: float | None = None


class DomicilioAdminListResponse(BaseModel):
    items: list[DomicilioAdminItem]
    total: int


class DomicilioCourierCard(BaseModel):
    idEntrega: int
    pedidoID: int
    numeroPedido: int
    codigoPedido: str | None = None
    destinatario: str | None = None
    direccion: str | None = None
    barrio: str | None = None
    telefonoDestino: str | None = None
    mensaje: str | None = None
    estado: str
    horaEntrega: str | None = None
    fechaEntregaProgramada: datetime | None = None


class DomicilioCourierListResponse(BaseModel):
    items: list[DomicilioCourierCard]
    total: int


class AsignarDomiciliarioRequest(BaseModel):
    domiciliarioID: int | None = None
    usuarioCambio: str = Field(min_length=2)


class MarcarEnRutaRequest(BaseModel):
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
