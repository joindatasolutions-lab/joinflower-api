from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from dotenv import load_dotenv
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.cliente import Cliente
from app.models.estadopedido import EstadoPedido
from app.models.pago import Pago
from app.models.pedido import Pedido
from app.schemas.payment import WompiConfirmPaymentRequest
from app.services.wompi_service import (
    WOMPI_CURRENCY,
    build_checkout_url,
    calculate_amount_in_cents,
    generate_reference,
    verify_wompi_transaction,
)


def _reload_env() -> None:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(dotenv_path=env_path, override=True)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def create_checkout_link(db: Session, pedido_id: int) -> dict:
    _reload_env()

    if int(pedido_id or 0) <= 0:
        raise HTTPException(status_code=400, detail="pedidoID es obligatorio")

    currency = WOMPI_CURRENCY

    pedido_row = (
        db.query(Pedido, Cliente)
        .outerjoin(Cliente, Cliente.idCliente == Pedido.clienteID)
        .filter(Pedido.idPedido == pedido_id)
        .first()
    )

    if not pedido_row:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")

    pedido, cliente = pedido_row
    customer_email = (cliente.email if cliente else None)
    if not customer_email:
        raise HTTPException(status_code=400, detail="El cliente no tiene email para checkout WOMPI")

    amount_in_cents = calculate_amount_in_cents(pedido.totalNeto)

    if amount_in_cents <= 0:
        raise HTTPException(status_code=400, detail="El pedido no tiene monto valido para pago")

    reference = generate_reference(int(pedido.idPedido))
    checkout_url = ""

    # Reintento corto por si una referencia llega a colisionar por concurrencia.
    for _ in range(3):
        checkout_url = build_checkout_url(
            reference=reference,
            amount_in_cents=amount_in_cents,
            email=customer_email,
        )

        if not db.query(Pago.idPago).filter(Pago.referencia == reference).first():
            break
        reference = generate_reference(int(pedido.idPedido))

    now = _utc_now()
    pago = Pago(
        empresaID=pedido.empresaID,
        pedidoID=pedido.idPedido,
        proveedor="WOMPI",
        referencia=reference,
        estado="PENDING",
        moneda=currency,
        monto=Decimal(pedido.totalNeto or 0),
        checkoutUrl=checkout_url,
        createdAt=now,
        updatedAt=now,
    )

    try:
        db.add(pago)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"No fue posible registrar el pago: {exc}")

    return {
        "pedidoID": int(pedido.idPedido),
        "referencia": reference,
        "monto": int(Decimal(pedido.totalNeto or 0)),
        "moneda": currency,
        "checkoutUrl": checkout_url,
    }


def _find_paid_state(db: Session) -> EstadoPedido | None:
    return (
        db.query(EstadoPedido)
        .filter(func.upper(EstadoPedido.nombreEstado).in_(["PAGADO", "APROBADO"]), EstadoPedido.activo == True)
        .order_by(EstadoPedido.idEstadoPedido.asc())
        .first()
    )


def confirm_payment(db: Session, payload: WompiConfirmPaymentRequest) -> dict:
    referencia = (payload.referencia or "").strip()
    if not referencia:
        raise HTTPException(status_code=400, detail="referencia es obligatoria")

    pago = db.query(Pago).filter(Pago.referencia == referencia).first()
    if not pago:
        raise HTTPException(status_code=404, detail="Pago no encontrado para la referencia dada")

    estado_wompi = str(payload.estado or "").strip().upper()
    if not estado_wompi:
        raise HTTPException(status_code=400, detail="estado es obligatorio")

    try:
        pago.estado = estado_wompi
        pago.transaccionID = payload.transaccionID or pago.transaccionID
        pago.rawRespuesta = payload.rawRespuesta or pago.rawRespuesta
        pago.updatedAt = _utc_now()

        if estado_wompi == "APPROVED":
            estado_pagado = _find_paid_state(db)
            if estado_pagado:
                pedido = db.query(Pedido).filter(Pedido.idPedido == pago.pedidoID).first()
                if pedido:
                    pedido.estadoPedidoID = estado_pagado.idEstadoPedido
                    pedido.updatedAt = _utc_now()

        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"No fue posible confirmar el pago: {exc}")

    return {
        "pedidoID": int(pago.pedidoID),
        "referencia": pago.referencia,
        "proveedor": pago.proveedor,
        "estado": pago.estado,
        "transaccionID": pago.transaccionID,
        "monto": float(pago.monto or 0),
        "moneda": pago.moneda,
        "updatedAt": pago.updatedAt,
    }


def get_payment_status(db: Session, referencia: str) -> dict:
    ref = (referencia or "").strip()
    if not ref:
        raise HTTPException(status_code=400, detail="referencia es obligatoria")

    pago = db.query(Pago).filter(Pago.referencia == ref).first()
    if not pago:
        raise HTTPException(status_code=404, detail="Pago no encontrado")

    return {
        "pedidoID": int(pago.pedidoID),
        "referencia": pago.referencia,
        "proveedor": pago.proveedor,
        "estado": pago.estado,
        "transaccionID": pago.transaccionID,
        "monto": float(pago.monto or 0),
        "moneda": pago.moneda,
        "updatedAt": pago.updatedAt,
    }


def verify_payment_transaction(transaction_id: str) -> dict:
    _reload_env()
    return verify_wompi_transaction(transaction_id=transaction_id)
