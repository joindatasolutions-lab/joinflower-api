from sqlalchemy import Column, BigInteger, DateTime, ForeignKey, String, Text
from app.database import Base


class ProduccionHistorial(Base):
    __tablename__ = "produccion_historial"
    __table_args__ = {"schema": "petalops"}

    idProduccionHistorial = Column("id_produccion_historial", BigInteger, primary_key=True, index=True)
    empresaID = Column("empresa_id", BigInteger, nullable=False, index=True)
    sucursalID = Column("sucursal_id", BigInteger, nullable=False, index=True)
    produccionID = Column("produccion_id", BigInteger, ForeignKey("petalops.produccion.id_produccion"), nullable=False, index=True)
    floristaAnteriorID = Column("florista_anterior_id", BigInteger, nullable=True)
    floristaNuevoID = Column("florista_nuevo_id", BigInteger, nullable=True)
    fechaCambio = Column("fecha_cambio", DateTime, nullable=False)
    motivo = Column(Text, nullable=False)
    usuarioCambio = Column("usuariocambio", String(120), nullable=False)
