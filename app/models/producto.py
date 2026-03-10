from sqlalchemy import Column, BigInteger, String, Numeric, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.database import Base


class Producto(Base):
    __tablename__ = "Producto"

    idProducto = Column(BigInteger, primary_key=True, index=True)
    empresaID = Column(BigInteger, ForeignKey("Empresa.idEmpresa"), nullable=False)
    codigoProducto = Column(String(50), nullable=False)
    categoriaID = Column(BigInteger, ForeignKey("Categoria.idCategoria"))
    nombreProducto = Column(String(200), nullable=False)
    descripcion = Column(Text)
    precioBase = Column("precio", Numeric(12,2), nullable=False)
    ivaIncluido = Column(Boolean)
    tiempoBaseProduccionMin = Column(BigInteger)
    nivelComplejidad = Column(String(30))
    activo = Column(Boolean, nullable=False)
    esDestacado = Column(Boolean)
    ordenCatalogo = Column(BigInteger)
    imagenUrl = Column(String(500))
    createdAt = Column(DateTime, nullable=False)
    updatedAt = Column(DateTime)

    empresa = relationship("Empresa", back_populates="productos")
    categoria = relationship("Categoria", back_populates="productos")
    detalles = relationship("PedidoDetalle", back_populates="producto")