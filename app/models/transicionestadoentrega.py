from sqlalchemy import Column, BigInteger, DateTime

from app.database import Base


class TransicionEstadoEntrega(Base):
    __tablename__ = "transicion_estado_entrega"
    __table_args__ = {"schema": "petalops"}

    idTrancisionEstadoEntrega = Column("id_tran_estado_ent", BigInteger, primary_key=True, index=True)
    empresaID = Column("empresa_id", BigInteger, nullable=False)
    estadoOrigenID = Column("estado_origen_id", BigInteger, nullable=False)
    estadoDestinoID = Column("estado_destino_id", BigInteger, nullable=False)
    createdAt = Column("created_at", DateTime, nullable=False)
