from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, String

from app.database import Base


class Proveedor(Base):
    __tablename__ = "Proveedor"

    idProveedor = Column(BigInteger, primary_key=True, index=True)
    empresaID = Column(BigInteger, ForeignKey("Empresa.idEmpresa"), nullable=False, index=True)
    nombreProveedor = Column(String(150), nullable=False)
    codigoProveedor = Column(String(80), nullable=True)
    activo = Column(Boolean, nullable=False, default=True)
    createdAt = Column(DateTime)
    updatedAt = Column(DateTime)
