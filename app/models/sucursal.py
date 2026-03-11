<<<<<<< HEAD
from sqlalchemy import Column, BigInteger, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
=======
from sqlalchemy import Column, BigInteger, String, DateTime
>>>>>>> origin/main

from app.database import Base


class Sucursal(Base):
    __tablename__ = "Sucursal"

    idSucursal = Column(BigInteger, primary_key=True, index=True)
<<<<<<< HEAD
    empresaID = Column(BigInteger, ForeignKey("Empresa.idEmpresa"), nullable=False)
    nombreSucursal = Column(String(120), nullable=False)
    direccion = Column(String(200))
    telefono = Column(String(30))
    estado = Column(String(30), nullable=False)
    createdAt = Column(DateTime, nullable=False)
    updatedAt = Column(DateTime)
    prefijoPedido = Column(String(12))

    empresa = relationship("Empresa", back_populates="sucursales")
    pedidos = relationship("Pedido", back_populates="sucursal")
    inventarios = relationship("Inventario", back_populates="sucursal")
    contadorPedido = relationship("SucursalContadorPedido", back_populates="sucursal", uselist=False)
=======
    empresaID = Column(BigInteger, nullable=False)
    nombreSucursal = Column(String(120))
    prefijoPedido = Column(String(12))
    direccion = Column(String(200))
    telefono = Column(String(30))
    estado = Column(String(30))
    createdAt = Column(DateTime)
    updatedAt = Column(DateTime)
>>>>>>> origin/main
