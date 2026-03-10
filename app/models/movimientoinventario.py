from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Numeric, String

from app.database import Base


class MovimientoInventario(Base):
    __tablename__ = "MovimientoInventario"

    idMovimiento = Column(BigInteger, primary_key=True, index=True)
    empresaID = Column(BigInteger, ForeignKey("Empresa.idEmpresa"), nullable=False, index=True)
    inventarioID = Column(BigInteger, ForeignKey("Inventario.idInventario"), nullable=False, index=True)
    tipoMovimiento = Column(String(20), nullable=False, index=True)
    cantidad = Column(Numeric(12, 2), nullable=False)
    fecha = Column(DateTime, nullable=False, index=True)
    motivo = Column(String(250), nullable=True)
    usuarioID = Column(BigInteger, ForeignKey("Usuario.idUsuario"), nullable=True, index=True)
    createdAt = Column(DateTime)
