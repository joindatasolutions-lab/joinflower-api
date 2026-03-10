from sqlalchemy import BigInteger, Boolean, Column, ForeignKey, String

from app.database import Base


class PermisoModulo(Base):
    __tablename__ = "PermisoModulo"

    rolID = Column(BigInteger, ForeignKey("Rol.idRol"), primary_key=True)
    modulo = Column(String(80), primary_key=True)
    puedeVer = Column(Boolean, nullable=False, default=False)
    puedeCrear = Column(Boolean, nullable=False, default=False)
    puedeEditar = Column(Boolean, nullable=False, default=False)
    puedeEliminar = Column(Boolean, nullable=False, default=False)
