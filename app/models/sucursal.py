from sqlalchemy import Column, BigInteger, String, DateTime

from app.database import Base


class Sucursal(Base):
    __tablename__ = "sucursal"
    __table_args__ = {"schema": "petalops"}

    idSucursal = Column("id_sucursal", BigInteger, primary_key=True, index=True)
    empresaID = Column("empresa_id", BigInteger, nullable=False, index=True)
    nombreSucursal = Column("nombre_sucursal", String(120), nullable=False)
    prefijoPedido = Column("prefijo_pedido", String(12))
    direccion = Column("direccion", String(200))
    telefono = Column("telefono", String(30))
    estado = Column("estado", String(30), nullable=False)
    createdAt = Column("created_at", DateTime)
    updatedAt = Column("updated_at", DateTime)
