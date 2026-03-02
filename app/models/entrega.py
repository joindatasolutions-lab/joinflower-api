from sqlalchemy import Column, BigInteger, DateTime, ForeignKey
from app.database import Base


class Entrega(Base):
    __tablename__ = "Entrega"

    idEntrega = Column(BigInteger, primary_key=True, index=True)
    empresaID = Column(BigInteger, ForeignKey("Empresa.idEmpresa"), nullable=False)
    pedidoID = Column(BigInteger, ForeignKey("Pedido.idPedido"), nullable=False)
    empleadoID = Column(BigInteger, nullable=True)
    estadoEntregaID = Column(BigInteger, nullable=False)
    fechaSalida = Column(DateTime)
    fechaEntrega = Column(DateTime)
    createdAt = Column(DateTime)
    updatedAt = Column(DateTime)
