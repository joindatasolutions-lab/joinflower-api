from sqlalchemy import Column, BigInteger, String, Numeric, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.database import Base


class Inventario(Base):
    __tablename__ = "Inventario"

    idInventario = Column(BigInteger, primary_key=True, index=True)
    empresaID = Column(BigInteger, ForeignKey("Empresa.idEmpresa"), nullable=False)
    insumoID = Column(BigInteger, ForeignKey("Insumo.idInsumo"), nullable=False)
    sucursalID = Column(BigInteger, ForeignKey("Sucursal.idSucursal"), nullable=False)
    stockActual = Column(Numeric(12, 4), nullable=False)
    stockReservado = Column(Numeric(12, 4), nullable=False)
    createdAt = Column(DateTime, nullable=False)
    updatedAt = Column(DateTime)
    codigo = Column(String(80), nullable=False, default="")
    nombre = Column(String(180), nullable=False, default="")
    categoria = Column(String(80), nullable=False, default="General")
    subcategoria = Column(String(80))
    color = Column(String(80))
    descripcion = Column(String(255))
    proveedorID = Column(BigInteger)
    codigoProveedor = Column(String(80))
    stockMinimo = Column(Numeric(12, 2), nullable=False, default=0)
    valorUnitario = Column(Numeric(12, 2), nullable=False, default=0)
    activo = Column(Boolean, nullable=False, default=True)
    fechaUltimaActualizacion = Column(DateTime)

    empresa = relationship("Empresa", back_populates="inventarios")
    insumo = relationship("Insumo", back_populates="inventarios")
    sucursal = relationship("Sucursal", back_populates="inventarios")
    movimientos = relationship("MovimientoInventario", back_populates="inventario")
