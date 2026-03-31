from sqlalchemy import BigInteger, Column, String, ForeignKey
from app.database import Base

class Plan(Base):
    __tablename__ = "Plan"
    __table_args__ = {"schema": "petalops"}

    planID = Column(BigInteger, primary_key=True)
    nombre = Column(String(100))  # Ajusta según tus columnas reales
    empresaID = Column(BigInteger, ForeignKey("petalops.Empresa.idEmpresa"))
