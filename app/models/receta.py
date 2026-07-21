from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Numeric, String, Text

from app.database import Base


class Receta(Base):
    __tablename__ = "receta"
    __table_args__ = {"schema": "petalops"}

    idReceta = Column("id_receta", BigInteger, primary_key=True, index=True)
    empresaID = Column("empresa_id", BigInteger, ForeignKey("petalops.empresa.id_empresa"), nullable=False, index=True)
    nombre = Column("nombre", String(200), nullable=False)
    descripcion = Column("descripcion", Text, nullable=True)
    productoID = Column("producto_id", BigInteger, ForeignKey("petalops.producto.id_producto"), nullable=True)
    capacidadManual = Column("capacidad_manual", Numeric(12, 2), nullable=True)
    activo = Column("activo", Boolean, nullable=False, default=True)
    createdAt = Column("created_at", DateTime, nullable=False)
    updatedAt = Column("updated_at", DateTime, nullable=True)


class RecetaDetalle(Base):
    __tablename__ = "receta_detalle"
    __table_args__ = {"schema": "petalops"}

    idRecetaDetalle = Column("id_receta_detalle", BigInteger, primary_key=True, index=True)
    empresaID = Column("empresa_id", BigInteger, ForeignKey("petalops.empresa.id_empresa"), nullable=False, index=True)
    recetaID = Column("receta_id", BigInteger, ForeignKey("petalops.receta.id_receta", ondelete="CASCADE"), nullable=False, index=True)
    inventarioID = Column("inventario_id", BigInteger, ForeignKey("petalops.inventario.id_inventario"), nullable=False)
    cantidad = Column("cantidad", Numeric(12, 4), nullable=False, default=1)
    createdAt = Column("created_at", DateTime, nullable=False)
