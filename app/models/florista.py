from sqlalchemy import Column, BigInteger, Integer, String, Boolean, DateTime, Text, Date
from app.database import Base


class Florista(Base):
    __tablename__ = "Florista"

    idFlorista = Column(BigInteger, primary_key=True, index=True)
    empresaID = Column(BigInteger, nullable=False, index=True)
    sucursalID = Column(BigInteger, nullable=False, index=True)
    nombre = Column(String(150), nullable=False)
    capacidadDiaria = Column(BigInteger, nullable=False)
    trabajosSimultaneosPermitidos = Column(Integer, nullable=False, default=1)
    estado = Column(String(20), nullable=False, default="Activo")
    fechaInicioIncapacidad = Column(Date)
    fechaFinIncapacidad = Column(Date)
    activo = Column(Boolean, nullable=False, default=True)
    especialidades = Column(Text)
    createdAt = Column(DateTime)
    updatedAt = Column(DateTime)
