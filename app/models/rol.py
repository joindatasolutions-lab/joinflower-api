from sqlalchemy import BigInteger, Column, ForeignKey, String

from app.database import Base


class Rol(Base):
    __tablename__ = "rol"
    __table_args__ = {"schema": "petalops"}

    # Mantener nombres legacy de atributos en Python.
    idRol = Column("id_rol", BigInteger, primary_key=True, index=True)
    empresaID = Column("empresa_id", BigInteger, ForeignKey("petalops.empresa.id_empresa"), nullable=False, index=True)
    nombreRol = Column("nombre_rol", String(80), nullable=False)
