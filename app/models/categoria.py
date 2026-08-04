from sqlalchemy import Column, BigInteger, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base


class Categoria(Base):
    __tablename__ = "categoria"
    __table_args__ = {"schema": "petalops"}

    idCategoria = Column("id_categoria", BigInteger, primary_key=True, index=True)
    empresaID = Column("empresa_id", BigInteger, ForeignKey("petalops.empresa.id_empresa"), nullable=False)

    nombreCategoria = Column("nombre", String(100), nullable=False)
    activo = Column("activo", Boolean)

    createdAt = Column("created_at", DateTime)

    # Relación inversa
    productos = relationship("Producto", back_populates="categoria")
