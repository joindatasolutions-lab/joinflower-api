from sqlalchemy import Boolean, Column, BigInteger, DateTime, ForeignKey, String

from app.database import Base


class Domiciliario(Base):
    __tablename__ = "Domiciliario"

    idDomiciliario = Column(BigInteger, primary_key=True, index=True)
    empresaID = Column(BigInteger, ForeignKey("Empresa.idEmpresa"), nullable=False, index=True)
    sucursalID = Column(BigInteger, nullable=False, index=True)
    nombre = Column(String(180), nullable=False)
    telefono = Column(String(40), nullable=True)
    activo = Column(Boolean, nullable=False, default=True)
    createdAt = Column(DateTime)
    updatedAt = Column(DateTime)
