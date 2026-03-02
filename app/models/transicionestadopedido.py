from sqlalchemy import Column, BigInteger, ForeignKey, DateTime
from app.database import Base


class TransicionEstadoPedido(Base):
    __tablename__ = "TransicionEstadoPedido"

    idTransicionEstadoPedido = Column(BigInteger, primary_key=True, index=True)

    empresaID = Column(BigInteger, nullable=False)
    estadoOrigenID = Column(BigInteger, nullable=False)
    estadoDestinoID = Column(BigInteger, nullable=False)

    createdAt = Column(DateTime)