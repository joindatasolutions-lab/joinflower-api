from sqlalchemy import Column, BigInteger, String, Numeric, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.database import Base


class Producto(Base):
    __tablename__ = "Producto"

    idProducto = Column(BigInteger, primary_key=True, index=True)
    empresaID = Column(BigInteger)
    codigoProducto = Column(String(50))
    categoriaID = Column(BigInteger, ForeignKey("Categoria.idCategoria"))
    nombreProducto = Column(String(200))
    descripcion = Column(Text)
    precioBase = Column("precio", Numeric(12,2))
    porcentajeIva = Column(Numeric(5,2))
    ivaIncluido = Column(Boolean)
    tiempoBaseProduccionMin = Column(BigInteger)
    nivelComplejidad = Column(String(30))
    activo = Column(Boolean)
    esDestacado = Column(Boolean)
    ordenCatalogo = Column(BigInteger)
    imagenUrl = Column(String(500))
    createdAt = Column(DateTime)
    updatedAt = Column(DateTime)

    categoria = relationship("Categoria", back_populates="productos")