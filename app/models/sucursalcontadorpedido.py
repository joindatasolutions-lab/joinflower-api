from sqlalchemy import Column, BigInteger, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.database import Base


class SucursalContadorPedido(Base):
    __tablename__ = "SucursalContadorPedido"

    empresaID = Column(BigInteger, ForeignKey("Empresa.idEmpresa"), primary_key=True)
    sucursalID = Column(BigInteger, ForeignKey("Sucursal.idSucursal"), primary_key=True)
    ultimoPedido = Column(BigInteger, nullable=False)
    updatedAt = Column(DateTime)

    empresa = relationship("Empresa")
    sucursal = relationship("Sucursal", back_populates="contadorPedido")
