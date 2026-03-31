from sqlalchemy import Column, BigInteger, DateTime, ForeignKey

from app.database import Base


class SucursalContadorPedido(Base):
    __tablename__ = "SucursalContadorPedido"
    __table_args__ = {"schema": "petalops"}

    empresaID = Column(BigInteger, ForeignKey("petalops.Empresa.idEmpresa"), primary_key=True)
    sucursalID = Column(BigInteger, ForeignKey("petalops.Sucursal.idSucursal"), primary_key=True)
    ultimoPedido = Column(BigInteger, nullable=False)
    updatedAt = Column(DateTime)
