from sqlalchemy import Column, BigInteger, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base

class Cliente(Base):
    __tablename__ = "Cliente"

    idCliente = Column(BigInteger, primary_key=True, index=True)
    empresaID = Column(BigInteger, ForeignKey("Empresa.idEmpresa"), nullable=False)
    tipoIdent = Column(String(30))
    identificacion = Column(String(50), nullable=False)
    indicativo = Column(String(10))
    telefonoCompleto = Column(String(40))
    nombreCompleto = Column(String(200), nullable=False)
    telefono = Column(String(30))
    email = Column(String(150))
    activo = Column(Boolean, nullable=False)
    createdAt = Column(DateTime, nullable=False)
    updatedAt = Column(DateTime)

    empresa = relationship("Empresa", back_populates="clientes")
    pedidos = relationship("Pedido", back_populates="cliente")