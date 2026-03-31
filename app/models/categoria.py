from sqlalchemy import Column, BigInteger, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base


class Categoria(Base):
    __tablename__ = "categoria"
    __table_args__ = {"schema": "petalops"}

    idCategoria = Column("idcategoria", BigInteger, primary_key=True, index=True)
    empresaID = Column("empresaid", BigInteger, ForeignKey("petalops.Empresa.idEmpresa"), nullable=False)

    nombreCategoria = Column("nombrecategoria", String(100), nullable=False)
    descripcion = Column("descripcion", String(250))
    orden = Column("orden", BigInteger)
    activo = Column("activo", Boolean)

    createdAt = Column("createdat", DateTime)
    updatedAt = Column("updatedat", DateTime)

    # Relación inversa
    productos = relationship("Producto", back_populates="categoria")
