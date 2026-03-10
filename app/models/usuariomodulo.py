from sqlalchemy import Column, BigInteger, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.database import Base


class UsuarioModulo(Base):
    __tablename__ = "UsuarioModulo"

    userID = Column(BigInteger, ForeignKey("Usuario.idUsuario"), primary_key=True)
    modulo = Column(String(80), primary_key=True)
    activo = Column(Boolean, nullable=False, default=True)
    updatedAt = Column(DateTime, nullable=False)

    usuario = relationship("Usuario", back_populates="modulos")
