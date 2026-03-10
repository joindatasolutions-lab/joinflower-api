from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.payment import (
    PaymentStatusResponse,
    WompiCheckoutLinkRequest,
    WompiCheckoutLinkResponse,
    WompiConfirmPaymentRequest,
    WompiVerifyResponse,
)
from app.services.payment_service import (
    confirm_payment,
    create_checkout_link,
    get_payment_status,
    verify_payment_transaction,
)

router = APIRouter(prefix="/pagos", tags=["pagos"])
api_router = APIRouter(prefix="/api/pagos", tags=["pagos"])


@router.post("/wompi/checkout-link", response_model=WompiCheckoutLinkResponse)
def wompi_checkout_link(payload: WompiCheckoutLinkRequest, db: Session = Depends(get_db)):
    """Genera URL firmada de Wompi para un pedido ya creado."""
    return create_checkout_link(db=db, pedido_id=payload.pedidoID)


@router.post("/wompi/confirmar", response_model=PaymentStatusResponse)
def wompi_confirmar(payload: WompiConfirmPaymentRequest, db: Session = Depends(get_db)):
    """Confirma/actualiza estado de pago y sincroniza estado del pedido."""
    return confirm_payment(db=db, payload=payload)


@router.get("/wompi/status", response_model=PaymentStatusResponse)
def wompi_status(referencia: str = Query(...), db: Session = Depends(get_db)):
    """Consulta estado de un pago por referencia."""
    return get_payment_status(db=db, referencia=referencia)


@api_router.get("/verificar", response_model=WompiVerifyResponse)
def wompi_verificar(id: str = Query(..., min_length=3)):
    """Verifica una transaccion de WOMPI por ID y retorna estado normalizado."""
    return verify_payment_transaction(transaction_id=id)
