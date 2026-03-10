from sqlalchemy import Column, BigInteger, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.database import Base


class EmpresaModulo(Base):
    __tablename__ = "EmpresaModulo"

    empresaID = Column(BigInteger, ForeignKey("Empresa.idEmpresa"), primary_key=True)
    modulo = Column(String(80), primary_key=True)
    activo = Column(Boolean, nullable=False, default=True)
    updatedAt = Column(DateTime, nullable=False)

    empresa = relationship("Empresa", back_populates="empresaModulos")
