from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, String

from app.database import Base


class UsuarioModulo(Base):
    __tablename__ = "usuario_modulo"
    __table_args__ = {"schema": "petalops"}

    userID = Column("usuario_id", BigInteger, ForeignKey("petalops.usuario.id_usuario"), primary_key=True)
    modulo = Column("modulo", String(80), primary_key=True)
    activo = Column("activo", Boolean, nullable=False, default=True)
    updatedAt = Column("updated_at", DateTime, nullable=False)
