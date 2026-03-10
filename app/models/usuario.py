from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, String

from app.database import Base


class Usuario(Base):
    __tablename__ = "Usuario"

    idUsuario = Column(BigInteger, primary_key=True, index=True)
    empresaID = Column(BigInteger, ForeignKey("Empresa.idEmpresa"), nullable=False, index=True)
    sucursalID = Column(BigInteger, nullable=False, index=True)
    nombre = Column(String(150), nullable=False)
    login = Column(String(80), nullable=False, unique=True, index=True)
    email = Column(String(180), nullable=False)
    passwordHash = Column(String(255), nullable=False)
    rolID = Column(BigInteger, ForeignKey("Rol.idRol"), nullable=False, index=True)
    estado = Column(String(20), nullable=False, default="Activo")
    ultimoLogin = Column(DateTime)
    createdAt = Column(DateTime)
    updatedAt = Column(DateTime)
