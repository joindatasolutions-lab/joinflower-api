from sqlalchemy import Column, BigInteger, String, Date, DateTime, ForeignKey, Text
from app.database import Base


class Produccion(Base):
    __tablename__ = "Produccion"

    idProduccion = Column(BigInteger, primary_key=True, index=True)
    empresaID = Column(BigInteger, nullable=False, index=True)
    sucursalID = Column(BigInteger, nullable=False, index=True)
    pedidoID = Column(BigInteger, ForeignKey("Pedido.idPedido"), nullable=False, index=True)
    floristaID = Column(BigInteger, ForeignKey("Florista.idFlorista"), nullable=True, index=True)
    fechaProgramadaProduccion = Column(Date, nullable=False, index=True)
    fechaAsignacion = Column(DateTime)
    fechaInicio = Column(DateTime)
    fechaFinalizacion = Column(DateTime)
    tiempoEstimadoMin = Column(BigInteger)
    tiempoRealMin = Column(BigInteger)
    estado = Column(String(30), nullable=False, index=True)
    prioridad = Column(String(20), nullable=False, default="MEDIA")
    observacionesInternas = Column(Text)
    ordenProduccion = Column(BigInteger)
    createdAt = Column(DateTime)
    updatedAt = Column(DateTime)
