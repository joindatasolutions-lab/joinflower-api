from sqlalchemy import Column, BigInteger, String, Boolean, DateTime
from app.database import Base


class EstadoPedido(Base):
    __tablename__ = "estado_pedido"
    __table_args__ = {"schema": "petalops"}

    idEstadoPedido = Column("id_estado_pedido", BigInteger, primary_key=True, index=True)
    nombreEstado = Column("nombre_estado", String(100), nullable=False)
    descripcion = Column("descripcion", String(250))
    orden = Column("orden", BigInteger)
    activo = Column("activo", Boolean)
    createdAt = Column("created_at", DateTime)
    updatedAt = Column("updated_at", DateTime)
