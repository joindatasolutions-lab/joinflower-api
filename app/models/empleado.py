from sqlalchemy import Column, BigInteger

from app.database import Base


class Empleado(Base):
    __tablename__ = "Empleado"
    __table_args__ = {"schema": "petalops"}

    idEmpleado = Column(BigInteger, primary_key=True, index=True)
