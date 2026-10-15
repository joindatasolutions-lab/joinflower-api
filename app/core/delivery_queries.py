from sqlalchemy import func
from sqlalchemy.orm import aliased

from app.models.entrega import Entrega
from app.models.pedido import Pedido


def current_delivery_id(db, pedido_model=Pedido):
    delivery = aliased(Entrega)
    return (
        db.query(delivery.idEntrega)
        .filter(delivery.empresaID == pedido_model.empresaID, delivery.pedidoID == pedido_model.idPedido)
        .order_by(delivery.intentoNumero.desc().nullslast(), delivery.idEntrega.desc())
        .limit(1).correlate(pedido_model).scalar_subquery()
    )


def latest_delivery_ids(db, empresa_id):
    ranked = db.query(
        Entrega.pedidoID.label("pedido_id"),
        Entrega.idEntrega.label("entrega_id"),
        func.row_number().over(
            partition_by=(Entrega.empresaID, Entrega.pedidoID),
            order_by=(Entrega.intentoNumero.desc().nullslast(), Entrega.idEntrega.desc()),
        ).label("position"),
    ).filter(Entrega.empresaID == int(empresa_id)).subquery()
    return db.query(ranked.c.pedido_id, ranked.c.entrega_id).filter(ranked.c.position == 1).subquery()
