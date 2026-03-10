from sqlalchemy import Column, BigInteger, String, Boolean, DateTime
from sqlalchemy.orm import relationship

from app.database import Base


class Empresa(Base):
    __tablename__ = "Empresa"

    idEmpresa = Column(BigInteger, primary_key=True, index=True)
    nombreEmpresa = Column(String(150), nullable=False)
    nit = Column(String(30), nullable=False)
    estado = Column(Boolean, nullable=False)
    createdAt = Column(DateTime, nullable=False)
    updatedAt = Column(DateTime, nullable=False)
    nombreComercial = Column(String(180))
    planID = Column(BigInteger)
    dominio = Column(String(120), index=True)
    slug = Column(String(50), unique=True, index=True)
    logoUrl = Column(String(500))

    sucursales = relationship("Sucursal", back_populates="empresa")
    clientes = relationship("Cliente", back_populates="empresa")
    pedidos = relationship("Pedido", back_populates="empresa")
    pagos = relationship("Pago", back_populates="empresa")
    productos = relationship("Producto", back_populates="empresa")
    usuarios = relationship("Usuario", back_populates="empresa")
    roles = relationship("Rol", back_populates="empresa")
    insumos = relationship("Insumo", back_populates="empresa")
    inventarios = relationship("Inventario", back_populates="empresa")
    domiciliarios = relationship("Domiciliario", back_populates="empresa")
    empresaModulos = relationship("EmpresaModulo", back_populates="empresa")
