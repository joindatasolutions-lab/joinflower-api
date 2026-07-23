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
    login: str | None = None
    nombre: str
    telefono: str | None = None
    tipo: str | None = None
    estado: str | None = None
    vehiculo: str | None = None
    placa: str | None = None
    detalleVehiculo: str | None = None
    pedidosActivos: int = 0
    activo: bool


class DomiciliarioListResponse(BaseModel):
    items: list[DomiciliarioItem]


class DomiciliarioUpdateRequest(BaseModel):
    nombre: str | None = Field(default=None, min_length=3)
    sucursalID: int | None = None
    telefono: str | None = Field(default=None, max_length=40)
    tipo: str | None = Field(default=None, max_length=80)
    estado: str | None = Field(default=None, max_length=20)
    vehiculo: str | None = Field(default=None, max_length=80)
    placa: str | None = Field(default=None, max_length=20)
    detalleVehiculo: str | None = Field(default=None, max_length=160)
    activo: bool | None = None


class DomiciliarioCreateRequest(BaseModel):
    nombre: str = Field(min_length=3)
    sucursalID: int | None = None
    telefono: str | None = Field(default=None, max_length=40)
    tipo: str | None = Field(default="Interno", max_length=80)
    estado: str | None = Field(default="Activo", max_length=20)
    vehiculo: str | None = Field(default=None, max_length=80)
    placa: str | None = Field(default=None, max_length=20)
    detalleVehiculo: str | None = Field(default=None, max_length=160)
    activo: bool = True


class DomiciliarioCreateResponse(DomiciliarioItem):
    passwordTemporal: str | None = None


class DomiciliarioDeleteResponse(BaseModel):
    status: str
    idDomiciliario: int
    estado: str


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
    arreglo: str | None = None
    nombreArreglo: str | None = None
    producto: str | None = None
    productos: list[str] = Field(default_factory=list)
    imageUrl: str | None = None
    imagenUrl: str | None = None
    imagenProductoUrl: str | None = None
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


class DomicilioMetricasResumen(BaseModel):
    total: int
    pendientes: int
    asignados: int
    enRuta: int
    entregados: int
    noEntregados: int
    cancelados: int
    novedades: int
    tasaEntrega: float
    tiempoPromedioEntregaMin: float | None = None
    costoDomicilioTotal: float
    costoDomicilioPromedio: float


class DomicilioMetricasItem(BaseModel):
    grupo: str
    periodo: str | None = None
    domiciliarioID: int | None = None
    domiciliario: str | None = None
    domiciliarioImagenUrl: str | None = None
    fotoUrl: str | None = None
    imageUrl: str | None = None
    estadoEntrega: str | None = None
    estadoPedido: str | None = None
    novedad: str | None = None
    barrioID: int | None = None
    barrio: str | None = None
    zonaID: int | None = None
    zona: str | None = None
    total: int
    pendientes: int
    asignados: int
    enRuta: int
    entregados: int
    noEntregados: int
    cancelados: int
    novedades: int
    tasaEntrega: float
    tiempoPromedioEntregaMin: float | None = None
    costoDomicilioTotal: float
    costoDomicilioPromedio: float


class DomicilioMetricasResponse(BaseModel):
    empresaID: int
    sucursalID: int | None = None
    fechaDesde: date
    fechaHasta: date
    agruparPor: str
    resumen: DomicilioMetricasResumen
    items: list[DomicilioMetricasItem]
    porDomiciliario: list[DomicilioMetricasItem]
    porEstadoEntrega: list[DomicilioMetricasItem]
    porEstadoPedido: list[DomicilioMetricasItem]
    porBarrio: list[DomicilioMetricasItem]
    porZona: list[DomicilioMetricasItem]
    novedades: list[DomicilioMetricasItem]


class PedidoDisponibleItem(BaseModel):
    id: int
    idEntrega: int | None = None
    pedidoID: int | None = None
    produccionID: int | None = None
    numeroPedido: str
    codigoPedido: str | None = None
    arreglo: str | None = None
    nombreArreglo: str | None = None
    producto: str | None = None
    productos: list[str] = Field(default_factory=list)
    imageUrl: str | None = None
    imagenUrl: str | None = None
    imagenProductoUrl: str | None = None
    cliente: str
    destinatario: str | None = None
    telefonoDestino: str | None = None
    telefonoDestinatario: str | None = None
    celularDestinatario: str | None = None
    direccion: str | None = None
    mensaje: str | None = None
    observacion: str | None = None
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
    latitudDestino: float | None = None
    longitudDestino: float | None = None


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
