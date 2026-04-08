from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.security import assert_same_empresa, get_current_auth_context, require_module_access
from app.database import get_db
from app.models.entrega import Entrega
from app.models.estadopedido import EstadoPedido
from app.models.pedido import Pedido
from app.schemas.entregas import EntregaMensajeResponse

router = APIRouter()


def _obtener_mensaje_tarjeta(
    pedido_id: int,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    pedido = db.query(Pedido).filter(Pedido.idPedido == pedido_id).first()
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")

    assert_same_empresa(auth, int(pedido.empresaID))

    estado_db = (
        db.query(EstadoPedido)
        .filter(EstadoPedido.idEstadoPedido == pedido.estadoPedidoID)
        .first()
    )

    estado_nombre = str((estado_db.nombreEstado if estado_db else "") or "").strip().upper()
    if estado_nombre not in {"APROBADO", "PAGADO"}:
        raise HTTPException(
            status_code=400,
            detail="El mensaje solo se puede consultar para pedidos en estado APROBADO/PAGADO",
        )

    entrega = (
        db.query(Entrega)
        .filter(Entrega.pedidoID == pedido.idPedido)
        .order_by(Entrega.intentoNumero.desc(), Entrega.idEntrega.desc())
        .first()
    )

    return EntregaMensajeResponse(
        pedidoId=int(pedido.idPedido),
        mensaje=str((entrega.mensaje if entrega else None) or ""),
        destinatario=str((entrega.destinatario if entrega else None) or ""),
        fechaEntrega=(entrega.fechaEntrega if entrega else None),
        firma=(str(entrega.firma) if entrega and entrega.firma is not None else None),
    )


@router.get(
    "/entregas/pedido/{pedido_id}/mensaje",
    response_model=EntregaMensajeResponse,
    dependencies=[Depends(require_module_access("pedidos", "puedeVer"))],
)
def obtener_mensaje_tarjeta(
    pedido_id: int,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    return _obtener_mensaje_tarjeta(pedido_id=pedido_id, db=db, auth=auth)


@router.get(
    "/pedido/{pedido_id}/mensaje",
    response_model=EntregaMensajeResponse,
    dependencies=[Depends(require_module_access("pedidos", "puedeVer"))],
)
def obtener_mensaje_tarjeta_alias(
    pedido_id: int,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    return _obtener_mensaje_tarjeta(pedido_id=pedido_id, db=db, auth=auth)
