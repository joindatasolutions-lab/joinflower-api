from sqlalchemy import Column, BigInteger, Integer, String, Boolean, DateTime
from sqlalchemy.orm import relationship
from app.database import Base


class EstadoPedido(Base):
    __tablename__ = "EstadoPedido"

    idEstadoPedido = Column(BigInteger, primary_key=True, index=True)
    nombreEstado = Column(String(100), nullable=False)
    descripcion = Column(String(250))
    orden = Column(Integer)
    activo = Column(Boolean)
    createdAt = Column(DateTime)
    updatedAt = Column(DateTime)

    pedidos = relationship("Pedido", back_populates="estadoPedido")