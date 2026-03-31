from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Numeric, String

from app.database import Base


class MovimientoInventario(Base):
    __tablename__ = "movimiento_inventario"
    __table_args__ = {"schema": "petalops"}

    idMovimiento = Column("id_movimiento", BigInteger, primary_key=True, index=True)
    empresaID = Column("empresa_id", BigInteger, ForeignKey("petalops.empresa.id_empresa"), nullable=False, index=True)
    inventarioID = Column("inventario_id", BigInteger, ForeignKey("petalops.inventario.id_inventario"), nullable=False, index=True)
    tipoMovimiento = Column("tipo_movimiento_id", BigInteger, nullable=True, index=True)
    cantidad = Column(Numeric(12, 2), nullable=False)
    fecha = Column(DateTime, nullable=False, index=True)
    motivo = Column(String(250), nullable=True)
    usuarioID = Column("usuario_id", BigInteger, ForeignKey("petalops.usuario.id_usuario"), nullable=True, index=True)
    createdAt = Column("created_at", DateTime)
