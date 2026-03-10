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
    row = (
        db.query(Pedido, Entrega, EstadoPedido)
        .outerjoin(Entrega, Entrega.pedidoID == Pedido.idPedido)
        .outerjoin(EstadoPedido, EstadoPedido.idEstadoPedido == Pedido.estadoPedidoID)
        .filter(Pedido.idPedido == pedido_id)
        .first()
    )

    if not row:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")

    pedido, entrega, estado_db = row
    assert_same_empresa(auth, int(pedido.empresaID))

    estado_nombre = str((estado_db.nombreEstado if estado_db else "") or "").strip().upper()
    if estado_nombre != "APROBADO":
        raise HTTPException(
            status_code=400,
            detail="El mensaje solo se puede consultar para pedidos en estado APROBADO",
        )

    if not entrega:
        raise HTTPException(status_code=404, detail="Entrega no encontrada para el pedido")

    return EntregaMensajeResponse(
        pedidoId=int(pedido.idPedido),
        mensaje=str(entrega.mensaje or ""),
        destinatario=str(entrega.destinatario or ""),
        fechaEntrega=entrega.fechaEntrega,
        firma=(str(entrega.firma) if entrega.firma is not None else None),
    )
