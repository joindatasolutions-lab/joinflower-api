from sqlalchemy import BigInteger, Boolean, Column, String

from app.database import Base


class PlanModulo(Base):
    __tablename__ = "plan_modulo"
    __table_args__ = {"schema": "petalops"}

    planID = Column("plan_id", BigInteger, primary_key=True)
    modulo = Column("modulo", String(80), primary_key=True)
    activo = Column("activo", Boolean, nullable=False, default=True)
    empresaID = Column("empresa_id", BigInteger, nullable=True, index=True)
