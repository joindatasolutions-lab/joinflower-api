from datetime import date, datetime, time

from pydantic import BaseModel, Field


class RegularizarEntregaPedidoInput(BaseModel):
    pedido_id: int = Field(gt=0)
    hora_entrega: time


class RegularizarEntregasRequest(BaseModel):
    fecha_entrega: date
    domiciliario_id: int = Field(gt=0)
    motivo: str | None = Field(default=None, min_length=10, max_length=1000)
    motivo_regularizacion: str | None = Field(default=None, min_length=10, max_length=1000)
    pedidos: list[RegularizarEntregaPedidoInput] | None = None
    pedido_id: int | None = Field(default=None, gt=0)
    hora_entrega: time | None = None


class RegularizarEntregaItemResponse(BaseModel):
    pedido_id: int
    entrega_id: int
    domiciliario_id: int
    estado_anterior: str
    estado_nuevo: str
    fecha_asignacion: datetime
    fecha_salida: datetime
    fecha_entrega: datetime
    regularizacion: bool = True


class RegularizarEntregasResponse(BaseModel):
    status: str
    total: int
    items: list[RegularizarEntregaItemResponse]
