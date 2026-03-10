from pydantic import BaseModel
from datetime import datetime


class EntregaMensajeResponse(BaseModel):
    pedidoId: int
    mensaje: str
    destinatario: str
    fechaEntrega: datetime | None = None
    firma: str | None = None
