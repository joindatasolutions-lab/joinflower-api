from sqlalchemy import Column, BigInteger, Numeric, DateTime, Date, Time, ForeignKey, String
from sqlalchemy.orm import relationship
from app.database import Base


class Pedido(Base):
    __tablename__ = "Pedido"

    idPedido = Column(BigInteger, primary_key=True, index=True)

    empresaID = Column(BigInteger, nullable=False)
    sucursalID = Column(BigInteger, nullable=False)
    clienteID = Column(BigInteger, ForeignKey("Cliente.idCliente"), nullable=False)

    fechaPedido = Column(DateTime)
    fechaPedidoDate = Column(Date)
    horaPedido = Column(Time)
    estadoPedidoID = Column(BigInteger, ForeignKey("EstadoPedido.idEstadoPedido"))
    version = Column(BigInteger, nullable=False, default=1)
    motivoRechazo = Column(String(300))

    totalBruto = Column(Numeric(12,2))
    totalIva = Column(Numeric(12,2))
    totalNeto = Column(Numeric(12,2))

    createdAt = Column(DateTime)
    updatedAt = Column(DateTime)

    detalles = relationship("PedidoDetalle", back_populates="pedido")