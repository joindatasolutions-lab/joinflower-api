from sqlalchemy import BigInteger, Column, ForeignKey, String

from app.database import Base


class Rol(Base):
    __tablename__ = "Rol"

    idRol = Column(BigInteger, primary_key=True, index=True)
    empresaID = Column(BigInteger, ForeignKey("Empresa.idEmpresa"), nullable=False, index=True)
    nombreRol = Column(String(80), nullable=False)
