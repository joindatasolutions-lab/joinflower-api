from sqlalchemy import Column, BigInteger

from app.database import Base


class Sucursal(Base):
    __tablename__ = "Sucursal"

    idSucursal = Column(BigInteger, primary_key=True, index=True)
