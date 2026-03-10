from sqlalchemy import Column, BigInteger, String, Boolean, DateTime, ForeignKey

from app.database import Base


class Proveedor(Base):
    __tablename__ = "Proveedor"

    idProveedor = Column(BigInteger, primary_key=True, index=True)
    empresaID = Column(BigInteger, ForeignKey("Empresa.idEmpresa"), nullable=False)
    nombreProveedor = Column(String(150), nullable=False)
    codigoProveedor = Column(String(80))
    activo = Column(Boolean, nullable=False, default=True)
    createdAt = Column(DateTime)
    updatedAt = Column(DateTime)
