from sqlalchemy import Column, BigInteger, String, Boolean, DateTime, ForeignKey

from app.database import Base


class Empleado(Base):
    __tablename__ = "Empleado"

    idEmpleado = Column(BigInteger, primary_key=True, index=True)
    empresaID = Column(BigInteger, ForeignKey("Empresa.idEmpresa"), nullable=False)
    sucursalID = Column(BigInteger, ForeignKey("Sucursal.idSucursal"))
    nombreEmpleado = Column(String(150), nullable=False)
    rol = Column(String(100), nullable=False)
    activo = Column(Boolean, nullable=False)
    createdAt = Column(DateTime, nullable=False)
    updatedAt = Column(DateTime)
