from sqlalchemy import BigInteger, Column, DateTime, Text

from app.database import Base


class PerfilFlorista(Base):
    __tablename__ = "perfil_florista"
    __table_args__ = {"schema": "petalops"}

    empleadoID = Column("empleado_id", BigInteger, primary_key=True, index=True)
    capacidadDiaria = Column("capacidad_diaria", BigInteger, nullable=False)
    trabajosSimultaneosPermitidos = Column("trab_simul_permi", BigInteger, nullable=False)
    especialidades = Column("especialidades", Text, nullable=True)
    fechaInicioIncapacidad = Column("fecha_ini_incap", DateTime, nullable=True)
    fechaFinIncapacidad = Column("fecha_fin_incap", DateTime, nullable=True)
