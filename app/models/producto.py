from sqlalchemy import Column, BigInteger, String, Numeric, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.database import Base


class Producto(Base):
    __tablename__ = "producto"
    __table_args__ = {"schema": "petalops"}

    idProducto = Column("id_producto", BigInteger, primary_key=True, index=True)
    empresaID = Column("empresa_id", BigInteger)
    categoriaID = Column("categoria_id", BigInteger, ForeignKey("petalops.categoria.idcategoria"))
    codigoProducto = Column("codigo_producto", String(50))
    codigoCatalogo = Column("codigo_catalogo", String(50))
    nombreProducto = Column("nombre_producto", String(200))
    descripcion = Column("descripcion", Text)
    porcentajeIva = Column("porcentaje_iva", Numeric(5,2))
    ivaIncluido = Column("iva_incluido", Boolean)
    tiempoBaseMin = Column("tiempo_base_min", BigInteger)
    nivelComplejidad = Column("nivel_complejidad", String(30))
    activo = Column("activo", Boolean)
    createdAt = Column("created_at", DateTime)
    updatedAt = Column("updated_at", DateTime)

    categoria = relationship("Categoria", back_populates="productos")
