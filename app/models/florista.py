from sqlalchemy import Boolean, Column, Date, DateTime, BigInteger, String, Text, literal
from sqlalchemy.orm import column_property
from app.database import Base


class Florista(Base):
    # Compatibilidad con esquema actual: no existe tabla florista,
    # se representa con empleados cuyo cargo es "Florista".
    __tablename__ = "empleado"
    __table_args__ = {"schema": "petalops"}

    idFlorista = Column("id_empleado", BigInteger, primary_key=True, index=True)
    empresaID = Column("empresa_id", BigInteger, nullable=False, index=True)
    sucursalID = Column("sucursal_id", BigInteger, nullable=True, index=True)
    nombre = Column("nombre_empleado", String(150), nullable=False)
    cargo = Column("cargo", String(100), nullable=False)
    activo = Column("activo", Boolean, nullable=False, default=True)
    createdAt = Column("created_at", DateTime)
    updatedAt = Column("updated_at", DateTime)

    # Campos de compatibilidad (tabla real vive en perfil_florista).
    capacidadDiaria = column_property(literal(1))
    trabajosSimultaneosPermitidos = column_property(literal(1))
    estado = column_property(literal("Activo"))
    fechaInicioIncapacidad = column_property(literal(None, type_=Date))
    fechaFinIncapacidad = column_property(literal(None, type_=Date))
    especialidades = column_property(literal(None, type_=Text))
