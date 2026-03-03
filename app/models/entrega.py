from sqlalchemy import Column, BigInteger, DateTime, ForeignKey, String, Text
from app.database import Base


class Entrega(Base):
    __tablename__ = "Entrega"

    idEntrega = Column(BigInteger, primary_key=True, index=True)
    empresaID = Column(BigInteger, ForeignKey("Empresa.idEmpresa"), nullable=False)
    pedidoID = Column(BigInteger, ForeignKey("Pedido.idPedido"), nullable=False)
    empleadoID = Column(BigInteger, nullable=True)
    estadoEntregaID = Column(BigInteger, nullable=False)
    tipoEntrega = Column(String(30), nullable=True)
    destinatario = Column(String(200), nullable=True)
    telefonoDestino = Column(String(30), nullable=True)
    direccion = Column(String(250), nullable=True)
    barrioID = Column(BigInteger, ForeignKey("Barrio.idBarrio"), nullable=True)
    barrioNombre = Column(String(150), nullable=True)
    rangoHora = Column(String(100), nullable=True)
    mensaje = Column(Text, nullable=True)
    firma = Column(String(150), nullable=True)
    observacionGeneral = Column(Text, nullable=True)
    fechaSalida = Column(DateTime)
    fechaEntrega = Column(DateTime)
    createdAt = Column(DateTime)
    updatedAt = Column(DateTime)
