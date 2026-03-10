from sqlalchemy import Column, BigInteger, String, DateTime, Numeric, ForeignKey
from sqlalchemy.orm import relationship

from app.database import Base


class Factura(Base):
    __tablename__ = "Factura"

    idFactura = Column(BigInteger, primary_key=True, index=True)
    empresaID = Column(BigInteger, ForeignKey("Empresa.idEmpresa"), nullable=False)
    pedidoID = Column(BigInteger, ForeignKey("Pedido.idPedido"), nullable=False)
    numeroFactura = Column(String(50), nullable=False)
    fechaFactura = Column(DateTime, nullable=False)
    totalFactura = Column(Numeric(12, 2), nullable=False)
    createdAt = Column(DateTime, nullable=False)
    updatedAt = Column(DateTime)

    empresa = relationship("Empresa")
    pedido = relationship("Pedido", back_populates="facturas")
