from sqlalchemy import Column, BigInteger, DateTime, Integer, String

from app.database import Base


class EstadoEntrega(Base):
    __tablename__ = "estado_entrega"
    __table_args__ = {"schema": "petalops"}

    idEstadoEntrega = Column("id_estado_entrega", BigInteger, primary_key=True, index=True)
    codigo = Column("codigo", String(30), nullable=False)
    nombre = Column("nombre", String(50), nullable=False)
    orden = Column("orden", Integer, nullable=True)
    createdAt = Column("created_at", DateTime, nullable=True)
