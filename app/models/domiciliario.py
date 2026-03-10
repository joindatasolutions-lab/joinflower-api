from sqlalchemy import Column, BigInteger, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.database import Base


class Domiciliario(Base):
    __tablename__ = "Domiciliario"

    idDomiciliario = Column(BigInteger, primary_key=True, index=True)
    empresaID = Column(BigInteger, ForeignKey("Empresa.idEmpresa"), nullable=False)
    sucursalID = Column(BigInteger, nullable=False)
    nombre = Column(String(180), nullable=False)
    telefono = Column(String(40))
    activo = Column(Boolean, nullable=False, default=True)
    createdAt = Column(DateTime)
    updatedAt = Column(DateTime)

    empresa = relationship("Empresa", back_populates="domiciliarios")
    entregas = relationship("Entrega", back_populates="domiciliario")
