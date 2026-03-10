from sqlalchemy import Column, BigInteger, Integer, String, Date, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.database import Base


class Produccion(Base):
    __tablename__ = "Produccion"

    idProduccion = Column(BigInteger, primary_key=True, index=True)
    empresaID = Column(BigInteger, ForeignKey("Empresa.idEmpresa"), nullable=False, index=True)
    sucursalID = Column(BigInteger, ForeignKey("Sucursal.idSucursal"), nullable=False, index=True)
    pedidoID = Column(BigInteger, index=True)
    floristaID = Column(BigInteger, nullable=True, index=True)
    fechaProgramadaProduccion = Column(Date, index=True)
    fechaAsignacion = Column(DateTime)
    pedidoDetalleID = Column(BigInteger, ForeignKey("PedidoDetalle.idPedidoDetalle"), index=True)
    empleadoID = Column(BigInteger, ForeignKey("Empleado.idEmpleado"), index=True)
    estadoProduccionID = Column(BigInteger)
    fechaInicio = Column(DateTime)
    fechaFinalizacion = Column(DateTime)
    tiempoEstimadoMin = Column(Integer)
    tiempoRealMin = Column(Integer)
    estado = Column(String(30), index=True)
    prioridad = Column(String(20), default="MEDIA")
    observacionesInternas = Column(Text)
    ordenProduccion = Column(BigInteger)
    fechaFin = Column(DateTime)
    createdAt = Column(DateTime, nullable=False)
    updatedAt = Column(DateTime)

    empresa = relationship("Empresa")
    sucursal = relationship("Sucursal")
    pedidoDetalle = relationship("PedidoDetalle", back_populates="producciones")
    entregas = relationship("Entrega", back_populates="produccion")
