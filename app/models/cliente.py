from sqlalchemy import Column, BigInteger, String, Boolean, DateTime, ForeignKey
from app.database import Base

class Cliente(Base):
    __tablename__ = "Cliente"

    idCliente = Column(BigInteger, primary_key=True, index=True)
    empresaID = Column(BigInteger, ForeignKey("Empresa.idEmpresa"))
    tipoIdent = Column(String(30))
    identificacion = Column(String(50))
    indicativo = Column(String(10))
    telefonoCompleto = Column(String(40))
    nombreCompleto = Column(String(150))
    telefono = Column(String(30))
    email = Column(String(150))
    activo = Column(Boolean)
    createdAt = Column(DateTime)
    updatedAt = Column(DateTime)