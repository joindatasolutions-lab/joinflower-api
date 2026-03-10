from sqlalchemy import Column, BigInteger, String, ForeignKey
from sqlalchemy.orm import relationship

from app.database import Base


class Rol(Base):
    __tablename__ = "Rol"

    idRol = Column(BigInteger, primary_key=True, index=True)
    empresaID = Column(BigInteger, ForeignKey("Empresa.idEmpresa"), nullable=False)
    nombreRol = Column(String(80), nullable=False)

    empresa = relationship("Empresa", back_populates="roles")
    usuarios = relationship("Usuario", back_populates="rol")
    permisos = relationship("PermisoModulo", back_populates="rol")
