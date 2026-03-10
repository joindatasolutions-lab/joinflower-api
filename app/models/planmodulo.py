from sqlalchemy import Column, BigInteger, String, Boolean

from app.database import Base


class PlanModulo(Base):
    __tablename__ = "PlanModulo"

    planID = Column(BigInteger, primary_key=True)
    modulo = Column(String(80), primary_key=True)
    activo = Column(Boolean, nullable=False, default=True)
