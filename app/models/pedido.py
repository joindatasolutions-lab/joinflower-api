from sqlalchemy import Column, BigInteger, Numeric, DateTime, ForeignKey, String
from sqlalchemy.orm import relationship
from app.database import Base


class Pedido(Base):
    __tablename__ = "Pedido"

    idPedido = Column(BigInteger, primary_key=True, index=True)

    empresaID = Column(BigInteger, nullable=False)
    sucursalID = Column(BigInteger, nullable=False)
    clienteID = Column(BigInteger, ForeignKey("Cliente.idCliente"), nullable=False)

    fechaPedido = Column(DateTime)
    estadoPedidoID = Column(BigInteger, ForeignKey("EstadoPedido.idEstadoPedido"))
    motivoRechazo = Column(String(300))

    totalBruto = Column(Numeric(12,2))
    totalIva = Column(Numeric(12,2))
    totalNeto = Column(Numeric(12,2))

    createdAt = Column(DateTime)
    updatedAt = Column(DateTime)

    detalles = relationship("PedidoDetalle", back_populates="pedido")