from sqlalchemy import Column, BigInteger, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import relationship
from app.database import Base


class Pago(Base):
    __tablename__ = "Pago"

    idPago = Column(BigInteger, primary_key=True, index=True)
    empresaID = Column(BigInteger, ForeignKey("Empresa.idEmpresa"), nullable=False)
    pedidoID = Column(BigInteger, ForeignKey("Pedido.idPedido"), nullable=False, index=True)
    proveedor = Column(String(50), nullable=False, default="WOMPI")
    referencia = Column(String(120), nullable=True)
    transaccionID = Column(String(120), nullable=True)
    estado = Column(String(40), nullable=False, default="PENDIENTE")
    moneda = Column(String(10), nullable=False, default="COP")
    monto = Column(Numeric(12, 2), nullable=False)
    checkoutUrl = Column(Text, nullable=True)
    rawRespuesta = Column(Text, nullable=True)
    metodoPago = Column(String(100), nullable=False)
    fechaPago = Column(DateTime, nullable=False)
    createdAt = Column(DateTime, nullable=False)
    updatedAt = Column(DateTime)

    empresa = relationship("Empresa", back_populates="pagos")
    pedido = relationship("Pedido", back_populates="pagos")
