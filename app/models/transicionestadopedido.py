from sqlalchemy import Column, BigInteger, ForeignKey, DateTime
from app.database import Base


class TransicionEstadoPedido(Base):
    __tablename__ = "transicion_estado_pedido"
    __table_args__ = {"schema": "petalops"}

    idTransicionEstadoPedido = Column("id_trans_estado_ped", BigInteger, primary_key=True, index=True)

    empresaID = Column("empresa_id", BigInteger, ForeignKey("petalops.empresa.id_empresa"), nullable=False)
    estadoOrigenID = Column("estado_origen_id", BigInteger, ForeignKey("petalops.estado_pedido.id_estado_pedido"), nullable=False)
    estadoDestinoID = Column("estado_destino_id", BigInteger, ForeignKey("petalops.estado_pedido.id_estado_pedido"), nullable=False)

    createdAt = Column("created_at", DateTime, nullable=False)
