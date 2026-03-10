from sqlalchemy import Column, BigInteger, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.database import Base


class Usuario(Base):
    __tablename__ = "Usuario"

    idUsuario = Column(BigInteger, primary_key=True, index=True)
    empresaID = Column(BigInteger, ForeignKey("Empresa.idEmpresa"), nullable=False)
    nombre = Column(String(150), nullable=False)
    email = Column(String(180), nullable=False)
    passwordHash = Column(String(255), nullable=False)
    rolID = Column(BigInteger, ForeignKey("Rol.idRol"), nullable=False)
    estado = Column(String(20), nullable=False, default="Activo")
    ultimoLogin = Column(DateTime)
    createdAt = Column(DateTime)
    updatedAt = Column(DateTime)
    login = Column(String(80), nullable=False)
    sucursalID = Column(BigInteger, nullable=False)

    empresa = relationship("Empresa", back_populates="usuarios")
    rol = relationship("Rol", back_populates="usuarios")
    movimientosInventario = relationship("MovimientoInventario", back_populates="usuario")
    modulos = relationship("UsuarioModulo", back_populates="usuario")
