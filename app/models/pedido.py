from sqlalchemy import Column, BigInteger, Numeric, DateTime, ForeignKey, String
from sqlalchemy.orm import relationship
from app.database import Base


class Pedido(Base):
    __tablename__ = "pedido"
    __table_args__ = {"schema": "petalops"}

    idPedido = Column("id_pedido", BigInteger, primary_key=True, index=True)

    empresaID = Column("empresa_id", BigInteger, nullable=False)
    sucursalID = Column("sucursal_id", BigInteger, nullable=False)
    numeroPedido = Column("numero_pedido", BigInteger, nullable=False)
    codigoPedido = Column("codigo_pedido", String(40))
    clienteID = Column("cliente_id", BigInteger, ForeignKey("petalops.cliente.cliente_id"), nullable=False)

    fechaPedido = Column("fecha_pedido", DateTime)
    estadoPedidoID = Column("estado_pedido_id", BigInteger, ForeignKey("petalops.estado_pedido.id_estado_pedido"))
    version = Column("version", BigInteger, nullable=False, default=1)
    motivoRechazo = Column("motivo_rechazo", String(300))

    totalBruto = Column("total_bruto", Numeric(12,2))
    totalIva = Column("total_iva", Numeric(12,2))
    totalNeto = Column("total_neto", Numeric(12,2))

    createdAt = Column("created_at", DateTime)
    updatedAt = Column("updated_at", DateTime)

    detalles = relationship("PedidoDetalle", back_populates="pedido")
