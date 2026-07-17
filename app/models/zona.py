from sqlalchemy import BigInteger, Column, String

from app.database import Base


class Zona(Base):
    __tablename__ = "zona"
    __table_args__ = {"schema": "petalops"}

    idZona = Column("id_zona", BigInteger, primary_key=True, index=True)
    nombreZona = Column("nombre_zona", String(150), nullable=False)
