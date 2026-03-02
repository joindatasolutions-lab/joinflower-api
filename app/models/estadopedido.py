from sqlalchemy import Column, BigInteger, String, Boolean, DateTime
from app.database import Base


class EstadoPedido(Base):
    __tablename__ = "EstadoPedido"

    idEstadoPedido = Column(BigInteger, primary_key=True, index=True)
    nombreEstado = Column(String(100), nullable=False)
    descripcion = Column(String(250))
    orden = Column(BigInteger)
    activo = Column(Boolean)
    createdAt = Column(DateTime)
    updatedAt = Column(DateTime)