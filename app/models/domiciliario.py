from sqlalchemy import Column, BigInteger, DateTime, ForeignKey, Integer, String

from app.database import Base


class Domiciliario(Base):
    # En el esquema actual no existe tabla domiciliario; se usa empleado con cargo='Domiciliario'.
    __tablename__ = "empleado"
    __table_args__ = {"schema": "petalops", "extend_existing": True}

    idDomiciliario = Column("id_empleado", BigInteger, primary_key=True, index=True)
    empresaID = Column("empresa_id", BigInteger, ForeignKey("petalops.empresa.id_empresa"), nullable=False, index=True)
    sucursalID = Column("sucursal_id", BigInteger, nullable=True, index=True)
    usuarioID = Column("usuario_id", BigInteger, nullable=True, index=True)
    nombre = Column("nombre_empleado", String(180), nullable=False)
    cargo = Column("cargo", String(100), nullable=False)
    telefono = Column("telefono", String(40), nullable=True)
    tipo = Column("tipo", String(80), nullable=True)
    estado = Column("estado", String(20), nullable=True)
    vehiculo = Column("vehiculo", String(80), nullable=True)
    activo = Column("activo", Integer, nullable=False, default=1)
    createdAt = Column("created_at", DateTime)
    updatedAt = Column("updated_at", DateTime)
