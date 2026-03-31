from sqlalchemy import Column, BigInteger, String, Numeric, Boolean, DateTime, ForeignKey

from app.database import Base


class Barrio(Base):
    __tablename__ = "Barrio"
    __table_args__ = {"schema": "petalops"}

    idBarrio = Column(BigInteger, primary_key=True, index=True)
    empresaID = Column(BigInteger, ForeignKey("petalops.Empresa.idEmpresa"), nullable=False)
    sucursalID = Column(BigInteger, ForeignKey("petalops.Sucursal.idSucursal"))
    zonaID = Column(BigInteger, nullable=False)
    nombreBarrio = Column(String(150), nullable=False)
    costoDomicilio = Column(Numeric(12, 2), nullable=False)
    activo = Column(Boolean, nullable=False)
    createdAt = Column(DateTime)
    updatedAt = Column(DateTime)
