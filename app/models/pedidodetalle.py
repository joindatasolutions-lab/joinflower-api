from sqlalchemy import Column, BigInteger, Numeric, ForeignKey
from sqlalchemy.orm import relationship, synonym
from app.database import Base


class PedidoDetalle(Base):
    __tablename__ = "PedidoDetalle"

    idPedidoDetalle = Column(BigInteger, primary_key=True, index=True)

    empresaID = Column(BigInteger, ForeignKey("Empresa.idEmpresa"), nullable=False)
    sucursalID = Column(BigInteger, ForeignKey("Sucursal.idSucursal"), nullable=False)
    pedidoID = Column(BigInteger, ForeignKey("Pedido.idPedido"), nullable=False)
    productoID = Column(BigInteger, ForeignKey("Producto.idProducto"), nullable=False)

    cantidad = Column(Numeric(12, 2), nullable=False)
    precioUnitario = Column(Numeric(12,2), nullable=False)
    ivaUnitario = Column(Numeric(12,2))
    subtotal = Column(Numeric(12,2), nullable=False)
    totalLinea = synonym("subtotal")

    pedido = relationship("Pedido", back_populates="detalles")
    producto = relationship("Producto", back_populates="detalles")
    producciones = relationship("Produccion", back_populates="pedidoDetalle")