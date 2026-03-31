from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Numeric, String

from app.database import Base


class Inventario(Base):
    __tablename__ = "inventario"
    __table_args__ = {"schema": "petalops"}

    idInventario = Column("id_inventario", BigInteger, primary_key=True, index=True)
    empresaID = Column("empresa_id", BigInteger, ForeignKey("petalops.empresa.id_empresa"), nullable=False, index=True)
    sucursalID = Column("sucursal_id", BigInteger, nullable=False, index=True)
    insumoID = Column("insumo_id", BigInteger, nullable=False, index=True)
    stockActual = Column("stock_actual", Numeric(12, 2), nullable=False, default=0)
    stockReservado = Column("stock_reservado", Numeric(12, 4), nullable=False, default=0)
    stockMinimo = Column("stock_minimo", Numeric(12, 2), nullable=False, default=0)
    valorUnitario = Column("valor_unitario", Numeric(12, 2), nullable=False, default=0)
    activo = Column(Boolean, nullable=False, default=True, index=True)
    fechaUltimaActualizacion = Column("fechaultimaactualizacion", DateTime)
    createdAt = Column("created_at", DateTime)
    updatedAt = Column("updated_at", DateTime)
