from sqlalchemy import Column, BigInteger, String, Numeric, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.database import Base


class Insumo(Base):
    __tablename__ = "Insumo"

    idInsumo = Column(BigInteger, primary_key=True, index=True)
    empresaID = Column(BigInteger, ForeignKey("Empresa.idEmpresa"), nullable=False)
    codigoBarra = Column(String(100))
    nombreInsumo = Column(String(200), nullable=False)
    unidadMedida = Column(String(50), nullable=False)
    stockMinimo = Column(Numeric(12, 4), nullable=False)
    activo = Column(Boolean, nullable=False)
    createdAt = Column(DateTime, nullable=False)
    updatedAt = Column(DateTime)

    empresa = relationship("Empresa", back_populates="insumos")
    inventarios = relationship("Inventario", back_populates="insumo")
