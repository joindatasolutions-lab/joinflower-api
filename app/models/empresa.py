from sqlalchemy import Column, BigInteger

from app.database import Base


class Empresa(Base):
    __tablename__ = "Empresa"

    idEmpresa = Column(BigInteger, primary_key=True, index=True)
