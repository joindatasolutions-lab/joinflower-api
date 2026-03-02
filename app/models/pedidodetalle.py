from sqlalchemy import Column, BigInteger, Numeric, ForeignKey
from sqlalchemy.orm import relationship, synonym
from app.database import Base


class PedidoDetalle(Base):
    __tablename__ = "PedidoDetalle"

    idPedidoDetalle = Column(BigInteger, primary_key=True, index=True)

    empresaID = Column(BigInteger, nullable=False)
    sucursalID = Column(BigInteger, nullable=False)
    pedidoID = Column(BigInteger, ForeignKey("Pedido.idPedido"))
    productoID = Column(BigInteger, ForeignKey("Producto.idProducto"))

    cantidad = Column(Numeric(12, 2))
    precioUnitario = Column(Numeric(12,2))
    ivaUnitario = Column(Numeric(12,2))
    subtotal = Column(Numeric(12,2))
    totalLinea = synonym("subtotal")

    pedido = relationship("Pedido", back_populates="detalles")