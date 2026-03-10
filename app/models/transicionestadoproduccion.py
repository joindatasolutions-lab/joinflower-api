from sqlalchemy import Column, BigInteger, DateTime, ForeignKey

from app.database import Base


class TransicionEstadoProduccion(Base):
    __tablename__ = "TransicionEstadoProduccion"

    idTransicionEstadoProduccion = Column(BigInteger, primary_key=True, index=True)
    empresaID = Column(BigInteger, ForeignKey("Empresa.idEmpresa"), nullable=False)
    estadoOrigenID = Column(BigInteger, nullable=False)
    estadoDestinoID = Column(BigInteger, nullable=False)
    createdAt = Column(DateTime, nullable=False)
