from sqlalchemy import Column, BigInteger, DateTime, ForeignKey, String, Text, Numeric
from sqlalchemy.orm import relationship
from app.database import Base


class Entrega(Base):
    __tablename__ = "Entrega"

    idEntrega = Column(BigInteger, primary_key=True, index=True)
    empresaID = Column(BigInteger, ForeignKey("Empresa.idEmpresa"), nullable=False)
    pedidoID = Column(BigInteger, ForeignKey("Pedido.idPedido"), nullable=False)
    empleadoID = Column(BigInteger, ForeignKey("Empleado.idEmpleado"), nullable=True)
    estadoEntregaID = Column(BigInteger, nullable=False)
    tipoEntrega = Column(String(30), nullable=True)
    destinatario = Column(String(200), nullable=True)
    telefonoDestino = Column(String(30), nullable=True)
    direccion = Column(String(250), nullable=True)
    barrioID = Column(BigInteger, nullable=True)
    barrioNombre = Column(String(150), nullable=True)
    fechaSalida = Column(DateTime)
    fechaEntrega = Column(DateTime)
    rangoHora = Column(String(100), nullable=True)
    mensaje = Column(Text, nullable=True)
    firma = Column(String(150), nullable=True)
    observacionGeneral = Column(Text, nullable=True)
    createdAt = Column(DateTime, nullable=False)
    updatedAt = Column(DateTime)
    sucursalID = Column(BigInteger)
    produccionID = Column(BigInteger, ForeignKey("Produccion.idProduccion"), nullable=True)
    domiciliarioID = Column(BigInteger, ForeignKey("Domiciliario.idDomiciliario"), nullable=True)
    fechaAsignacion = Column(DateTime)
    fechaEntregaProgramada = Column(DateTime)
    estado = Column(String(30))
    latitudEntrega = Column(Numeric(10, 7))
    longitudEntrega = Column(Numeric(10, 7))
    firmaNombre = Column(String(180))
    firmaDocumento = Column(String(50))
    firmaImagenUrl = Column(Text)
    evidenciaFotoUrl = Column(Text)
    observaciones = Column(Text)
    motivoNoEntregado = Column(Text)
    intentoNumero = Column(BigInteger, nullable=False, default=1)
    reprogramadaPara = Column(DateTime)

    pedido = relationship("Pedido", back_populates="entrega")
    produccion = relationship("Produccion", back_populates="entregas")
    domiciliario = relationship("Domiciliario", back_populates="entregas")
