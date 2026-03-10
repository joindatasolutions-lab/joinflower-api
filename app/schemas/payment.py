from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class WompiCheckoutLinkRequest(BaseModel):
    pedidoID: int


class WompiCheckoutLinkResponse(BaseModel):
    pedidoID: int
    referencia: str
    monto: int
    moneda: str
    checkoutUrl: str


class WompiConfirmPaymentRequest(BaseModel):
    referencia: str
    transaccionID: Optional[str] = None
    estado: str
    rawRespuesta: Optional[str] = None


class PaymentStatusResponse(BaseModel):
    pedidoID: int
    referencia: str
    proveedor: str
    estado: str
    transaccionID: Optional[str] = None
    monto: float
    moneda: str
    updatedAt: Optional[datetime] = None


class WompiVerifyResponse(BaseModel):
    id: str
    status: str
    providerStatus: str
