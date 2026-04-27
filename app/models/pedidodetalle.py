from sqlalchemy import Column, BigInteger, Numeric, ForeignKey, Text
from sqlalchemy.orm import relationship, synonym
from app.database import Base


class PedidoDetalle(Base):
    __tablename__ = "pedido_detalle"
    __table_args__ = {"schema": "petalops"}

    idPedidoDetalle = Column("id_pedido_detalle", BigInteger, primary_key=True, index=True)

    empresaID = Column("empresa_id", BigInteger, nullable=False)
    sucursalID = Column("sucursal_id", BigInteger, nullable=False)
    pedidoID = Column("pedido_id", BigInteger, ForeignKey("petalops.pedido.id_pedido"))
    productoID = Column("producto_id", BigInteger, ForeignKey("petalops.producto.id_producto"))

    cantidad = Column("cantidad", Numeric(12, 2))
    precioUnitario = Column("precio_unitario", Numeric(12,2))
    ivaUnitario = Column("iva_unitario", Numeric(12,2))
    subtotal = Column("subtotal", Numeric(12,2))
    observacionesPersonalizados = Column("observaciones_personalizados", Text, nullable=True)
    totalLinea = synonym("subtotal")

    pedido = relationship("Pedido", back_populates="detalles")
