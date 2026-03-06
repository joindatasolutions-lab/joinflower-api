from sqlalchemy import Column, BigInteger, DateTime, ForeignKey, String, Text
from app.database import Base


class ProduccionHistorial(Base):
    __tablename__ = "ProduccionHistorial"

    idProduccionHistorial = Column(BigInteger, primary_key=True, index=True)
    empresaID = Column(BigInteger, nullable=False, index=True)
    sucursalID = Column(BigInteger, nullable=False, index=True)
    produccionID = Column(BigInteger, ForeignKey("Produccion.idProduccion"), nullable=False, index=True)
    floristaAnteriorID = Column(BigInteger, ForeignKey("Florista.idFlorista"), nullable=True)
    floristaNuevoID = Column(BigInteger, ForeignKey("Florista.idFlorista"), nullable=True)
    fechaCambio = Column(DateTime, nullable=False)
    motivo = Column(Text, nullable=False)
    usuarioCambio = Column(String(120), nullable=False)
