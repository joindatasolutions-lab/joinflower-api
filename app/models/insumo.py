from sqlalchemy import BigInteger, Boolean, Column, Date, DateTime, ForeignKey, Numeric, String, Text

from app.database import Base


class Insumo(Base):
    __tablename__ = "insumo"
    __table_args__ = {"schema": "petalops"}

    idInsumo = Column("id_insumo", BigInteger, primary_key=True, index=True)
    empresaID = Column("empresa_id", BigInteger, ForeignKey("petalops.empresa.id_empresa"), nullable=False, index=True)
    nombreInsumo = Column("nombre_insumo", String(200), nullable=False)
    codigoBarra = Column("codigo_barra", String(100), nullable=True)
    unidadMedida = Column("unidad_medida", String(50), nullable=False)
    categoria = Column("categoria", String(80), nullable=True)
    subcategoria = Column("subcategoria", String(80), nullable=True)
    color = Column("color", String(80), nullable=True)
    descripcion = Column("descripcion", Text, nullable=True)
    tamano = Column("tamano", String(50), nullable=True)
    fechaVencimiento = Column("fecha_vencimiento", Date, nullable=True)
    marca = Column("marca", String(100), nullable=True)
    precioVenta = Column("precio_venta", Numeric(12, 2), nullable=True)
    proveedorID = Column("proveedor_id", BigInteger, ForeignKey("petalops.proveedor.id_proveedor"), nullable=True, index=True)
    activo = Column("activo", Boolean, nullable=False, default=True)
    createdAt = Column("created_at", DateTime)
    updatedAt = Column("updated_at", DateTime)
