from sqlalchemy import Column, BigInteger

from app.database import Base


class Empleado(Base):
    __tablename__ = "Empleado"

    idEmpleado = Column(BigInteger, primary_key=True, index=True)
