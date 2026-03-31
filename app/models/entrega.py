from sqlalchemy import Column, BigInteger, DateTime, ForeignKey, Integer, Numeric, String, Text
from app.database import Base


class Entrega(Base):
    __tablename__ = "entrega"
    __table_args__ = {"schema": "petalops"}

    idEntrega = Column("id_entrega", BigInteger, primary_key=True, index=True)
    empresaID = Column("empresa_id", BigInteger, ForeignKey("petalops.empresa.id_empresa"), nullable=False)
    sucursalID = Column("sucursalid", BigInteger, nullable=True, index=True)
    pedidoID = Column("pedido_id", BigInteger, ForeignKey("petalops.pedido.id_pedido"), nullable=False)
    produccionID = Column("produccionid", BigInteger, nullable=True, index=True)
    domiciliarioID = Column("domiciliarioid", BigInteger, nullable=True, index=True)
    empleadoID = Column("empleado_id", BigInteger, nullable=True)
    estadoEntregaID = Column("estadoentregaid", BigInteger, nullable=False)
    tipoEntrega = Column("tipoentrega", String(30), nullable=True)
    destinatario = Column("destinatario", String(200), nullable=True)
    telefonoDestino = Column("telefonodestino", String(30), nullable=True)
    direccion = Column("direccion", String(250), nullable=True)
    barrioID = Column("barrioid", BigInteger, nullable=True)
    barrioNombre = Column("barrionombre", String(150), nullable=True)
    rangoHora = Column("rangohora", String(100), nullable=True)
    mensaje = Column("mensaje", Text, nullable=True)
    firma = Column("firma", String(150), nullable=True)
    observacionGeneral = Column("observaciongeneral", Text, nullable=True)
    fechaAsignacion = Column("fechaasignacion", DateTime)
    fechaSalida = Column("fechasalida", DateTime)
    fechaEntregaProgramada = Column("fechaentregaprogramada", DateTime)
    fechaEntrega = Column("fechaentrega", DateTime)
    latitudEntrega = Column("latitudentrega", Numeric(10, 7), nullable=True)
    longitudEntrega = Column("longitudentrega", Numeric(10, 7), nullable=True)
    firmaNombre = Column("firmanombre", String(180), nullable=True)
    firmaDocumento = Column("firmadocumento", String(50), nullable=True)
    firmaImagenUrl = Column("firmaimagenurl", Text, nullable=True)
    evidenciaFotoUrl = Column("evidenciafotourl", Text, nullable=True)
    observaciones = Column("observaciones", Text, nullable=True)
    motivoNoEntregado = Column("motivonoentregado", Text, nullable=True)
    intentoNumero = Column("intentonumero", Integer, nullable=False, default=1)
    reprogramadaPara = Column("reprogramadapara", DateTime)
    createdAt = Column("createdat", DateTime)
    updatedAt = Column("updatedat", DateTime)
