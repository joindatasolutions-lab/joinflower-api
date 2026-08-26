from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey

from app.database import Base


class UsuarioRol(Base):
    __tablename__ = "usuario_rol"
    __table_args__ = {"schema": "petalops"}

    usuarioID = Column("usuario_id", BigInteger, ForeignKey("petalops.usuario.id_usuario"), primary_key=True)
    rolID = Column("rol_id", BigInteger, ForeignKey("petalops.rol.id_rol"), primary_key=True)
    empresaID = Column("empresa_id", BigInteger, ForeignKey("petalops.empresa.id_empresa"), nullable=False, index=True)
    principal = Column("principal", Boolean, nullable=False, default=False)
    activo = Column("activo", Boolean, nullable=False, default=True)
    createdAt = Column("created_at", DateTime)
    updatedAt = Column("updated_at", DateTime)
