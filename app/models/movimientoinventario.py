from sqlalchemy import Column, BigInteger, String, Numeric, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.database import Base


class MovimientoInventario(Base):
    __tablename__ = "MovimientoInventario"

    idMovimiento = Column(BigInteger, primary_key=True, index=True)
    empresaID = Column(BigInteger, ForeignKey("Empresa.idEmpresa"), nullable=False)
    inventarioID = Column(BigInteger, ForeignKey("Inventario.idInventario"), nullable=False)
    tipoMovimiento = Column(String(20), nullable=False)
    cantidad = Column(Numeric(12, 2), nullable=False)
    fecha = Column(DateTime, nullable=False)
    motivo = Column(String(250))
    usuarioID = Column(BigInteger, ForeignKey("Usuario.idUsuario"))
    createdAt = Column(DateTime)

    inventario = relationship("Inventario", back_populates="movimientos")
    usuario = relationship("Usuario", back_populates="movimientosInventario")
