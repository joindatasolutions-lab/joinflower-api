from sqlalchemy import BigInteger, Boolean, Column, ForeignKey, String

from app.database import Base


class PermisoModulo(Base):
    __tablename__ = "permiso_modulo"
    __table_args__ = {"schema": "petalops"}

    rolID = Column("rol_id", BigInteger, ForeignKey("petalops.rol.id_rol"), primary_key=True)
    modulo = Column("modulo", String(80), primary_key=True)
    puedeVer = Column("puede_ver", Boolean, nullable=False, default=False)
    puedeCrear = Column("puede_crear", Boolean, nullable=False, default=False)
    puedeEditar = Column("puede_editar", Boolean, nullable=False, default=False)
    puedeEliminar = Column("puede_eliminar", Boolean, nullable=False, default=False)
    empresaID = Column("empresa_id", BigInteger, nullable=True, index=True)
