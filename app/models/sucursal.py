from sqlalchemy import Column, BigInteger, String, DateTime

from app.database import Base


class Sucursal(Base):
    __tablename__ = "Sucursal"

    idSucursal = Column(BigInteger, primary_key=True, index=True)
    empresaID = Column(BigInteger, nullable=False)
    nombreSucursal = Column(String(120))
    prefijoPedido = Column(String(12))
    direccion = Column(String(200))
    telefono = Column(String(30))
    estado = Column(String(30))
    createdAt = Column(DateTime)
    updatedAt = Column(DateTime)
