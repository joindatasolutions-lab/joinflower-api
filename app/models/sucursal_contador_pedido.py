from sqlalchemy import Column, BigInteger, DateTime, ForeignKey

from app.database import Base


class SucursalContadorPedido(Base):
    __tablename__ = "SucursalContadorPedido"

    empresaID = Column(BigInteger, ForeignKey("Empresa.idEmpresa"), primary_key=True)
    sucursalID = Column(BigInteger, ForeignKey("Sucursal.idSucursal"), primary_key=True)
    ultimoPedido = Column(BigInteger, nullable=False)
    updatedAt = Column(DateTime)
