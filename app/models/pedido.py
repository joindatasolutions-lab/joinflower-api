from sqlalchemy import Column, BigInteger, Numeric, DateTime, Date, Time, ForeignKey, String
from sqlalchemy.orm import relationship
from app.database import Base


class Pedido(Base):
    __tablename__ = "Pedido"

    idPedido = Column(BigInteger, primary_key=True, index=True)

    empresaID = Column(BigInteger, ForeignKey("Empresa.idEmpresa"), nullable=False)
    sucursalID = Column(BigInteger, ForeignKey("Sucursal.idSucursal"), nullable=False)
    clienteID = Column(BigInteger, ForeignKey("Cliente.idCliente"), nullable=False)

    fechaPedido = Column(DateTime, nullable=False)
    fechaPedidoDate = Column(Date)
    horaPedido = Column(Time)
    estadoPedidoID = Column(BigInteger, ForeignKey("EstadoPedido.idEstadoPedido"), nullable=False)
    version = Column(BigInteger, nullable=False, default=1)
    motivoRechazo = Column(String(300))

    totalBruto = Column(Numeric(12,2), nullable=False)
    totalIva = Column(Numeric(12,2), nullable=False)
    totalNeto = Column(Numeric(12,2), nullable=False)
    numeroPedido = Column(BigInteger, nullable=False)
    codigoPedido = Column(String(40))

    createdAt = Column(DateTime, nullable=False)
    updatedAt = Column(DateTime)

    empresa = relationship("Empresa", back_populates="pedidos")
    sucursal = relationship("Sucursal", back_populates="pedidos")
    cliente = relationship("Cliente", back_populates="pedidos")
    estadoPedido = relationship("EstadoPedido", back_populates="pedidos")
    detalles = relationship("PedidoDetalle", back_populates="pedido")
    pagos = relationship("Pago", back_populates="pedido")
    facturas = relationship("Factura", back_populates="pedido")
    entrega = relationship("Entrega", back_populates="pedido", uselist=False)