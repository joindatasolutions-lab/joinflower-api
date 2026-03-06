from datetime import date, datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class ProduccionGenerarRequest(BaseModel):
    empresaID: int
    sucursalID: Optional[int] = None
    diasAnticipacion: Optional[int] = Field(default=None, ge=0, le=30)
    autoAsignar: bool = True


class ProduccionAsignarRequest(BaseModel):
    floristaID: Optional[int] = None
    fechaProgramadaProduccion: Optional[date] = None
    prioridad: Optional[str] = None
    observacionesInternas: Optional[str] = None
    motivo: Optional[str] = None
    usuarioCambio: Optional[str] = None


class ProduccionReasignarRequest(BaseModel):
    floristaNuevoID: Optional[int] = None
    fechaProgramadaProduccion: Optional[date] = None
    motivo: str
    usuarioCambio: str


class ProduccionEstadoRequest(BaseModel):
    nuevoEstado: str
    observacionesInternas: Optional[str] = None


class FloristaEstadoRequest(BaseModel):
    estado: str
    fechaInicioIncapacidad: Optional[date] = None
    fechaFinIncapacidad: Optional[date] = None
    motivo: Optional[str] = None
    usuarioCambio: str


class ProduccionRecalcularPedidoRequest(BaseModel):
    usuarioCambio: str
    motivo: Optional[str] = None
    productoEstructuralCambiado: bool = False
    forceCancelarYCrearNueva: bool = False


class ProduccionItem(BaseModel):
    idProduccion: int
    pedidoID: int
    numeroPedido: str
    producto: str
    cliente: str
    fechaEntrega: Optional[datetime] = None
    horaEntrega: Optional[str] = None
    floristaAsignado: Optional[str] = None
    estado: str
    fechaAsignacion: Optional[datetime] = None
    tiempoRestanteHoras: Optional[int] = None
    tiempoEstimadoMin: Optional[int] = None
    tiempoRealMin: Optional[int] = None
    prioridad: str
    fechaProgramadaProduccion: date


class ProduccionListResponse(BaseModel):
    items: List[ProduccionItem]
    total: int


class ProduccionResumenResponse(BaseModel):
    pendiente: int
    enProduccion: int
    paraEntrega: int
    cancelado: int


class ProduccionKanbanResponse(BaseModel):
    pendiente: List[ProduccionItem]
    enProduccion: List[ProduccionItem]
    paraEntrega: List[ProduccionItem]
    cancelado: List[ProduccionItem]


class FloristaItem(BaseModel):
    idFlorista: int
    nombre: str
    capacidadDiaria: int
    trabajosSimultaneosPermitidos: int = 1
    estado: str = "Activo"
    fechaInicioIncapacidad: Optional[date] = None
    fechaFinIncapacidad: Optional[date] = None
    activo: bool
    especialidades: Optional[str] = None


class FloristaListResponse(BaseModel):
    items: List[FloristaItem]


class ReasignacionHistorialItem(BaseModel):
    produccionID: int
    floristaAnteriorID: Optional[int] = None
    floristaNuevoID: Optional[int] = None
    fechaCambio: datetime
    motivo: str
    usuarioCambio: str


class ReasignacionHistorialResponse(BaseModel):
    items: List[ReasignacionHistorialItem]
    total: int


class FloristaProductividadItem(BaseModel):
    floristaID: int
    florista: str
    completadas: int
    tiempoPromedioRealMin: float
    cumplimientoPct: float
    reasignaciones: int
    cancelaciones: int


class FloristaProductividadResponse(BaseModel):
    items: List[FloristaProductividadItem]


class OperativaDiariaItem(BaseModel):
    fechaProgramadaProduccion: date
    capacidadTotal: int
    cargaAsignada: int
    capacidadUtilizadaPct: float
    sobrecarga: int
    retrasos: int
    produccionPromedioDiaria: float


class OperativaDiariaResponse(BaseModel):
    items: List[OperativaDiariaItem]
