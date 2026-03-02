from sqlalchemy import Column, BigInteger, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base


class Categoria(Base):
    __tablename__ = "Categoria"

    idCategoria = Column(BigInteger, primary_key=True, index=True)
    empresaID = Column(BigInteger, ForeignKey("Empresa.idEmpresa"), nullable=False)

    nombreCategoria = Column(String(100), nullable=False)
    descripcion = Column(String(250))
    orden = Column(BigInteger)
    activo = Column(Boolean)

    createdAt = Column(DateTime)
    updatedAt = Column(DateTime)

    # Relación inversa
    productos = relationship("Producto", back_populates="categoria")