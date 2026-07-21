from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


PipelineStage = Literal[
    "creado",
    "aprobado",
    "pendiente_produccion",
    "en_produccion",
    "listo",
    "en_camino",
    "entregado",
    "cancelado",
]


class PipelinePedidoCard(BaseModel):
    id_pedido: int
    numero_pedido: int
    cliente_nombre: str
    telefono: str | None = None
    fecha_entrega: datetime | None = None
    hora_entrega: str | None = None
    rango_hora: str | None = None
    direccion: str | None = None
    total: float
    estado: str
    sucursal: str | None = None
    sucursal_id: int | None = None
    domiciliario: str | None = None
    domiciliario_id: int | None = None
    florista_id: int | None = None
    prioridad: str | None = None
    urgente: bool = False
    tiempo_estimado_produccion: int | None = None
    tiempo_restante_entrega: int | None = None
    progreso_porcentaje: int = 0
    resumen_productos: str | None = None
    imagen_url: str | None = None
    color_estado: str
    tiene_tarjeta: bool = False
    es_domicilio: bool = True
    stage: PipelineStage


class PipelinePedidosResponse(BaseModel):
    creado: list[PipelinePedidoCard]
    aprobado: list[PipelinePedidoCard]
    pendiente_produccion: list[PipelinePedidoCard]
    en_produccion: list[PipelinePedidoCard]
    listo: list[PipelinePedidoCard]
    en_camino: list[PipelinePedidoCard]
    entregado: list[PipelinePedidoCard]
    cancelado: list[PipelinePedidoCard]

