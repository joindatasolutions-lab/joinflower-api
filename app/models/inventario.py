from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Numeric, String

from app.database import Base


class Inventario(Base):
    __tablename__ = "Inventario"

    idInventario = Column(BigInteger, primary_key=True, index=True)
    empresaID = Column(BigInteger, ForeignKey("Empresa.idEmpresa"), nullable=False, index=True)
    codigo = Column(String(80), nullable=False, index=True)
    nombre = Column(String(180), nullable=False)
    categoria = Column(String(80), nullable=False, index=True)
    subcategoria = Column(String(80), nullable=True)
    color = Column(String(80), nullable=True)
    descripcion = Column(String(255), nullable=True)
    proveedorID = Column(BigInteger, ForeignKey("Proveedor.idProveedor"), nullable=True, index=True)
    codigoProveedor = Column(String(80), nullable=True)
    stockActual = Column(Numeric(12, 2), nullable=False, default=0)
    stockMinimo = Column(Numeric(12, 2), nullable=False, default=0)
    valorUnitario = Column(Numeric(12, 2), nullable=False, default=0)
    activo = Column(Boolean, nullable=False, default=True, index=True)
    fechaUltimaActualizacion = Column(DateTime)
    createdAt = Column(DateTime)
    updatedAt = Column(DateTime)
