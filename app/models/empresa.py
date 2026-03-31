from sqlalchemy import Column, BigInteger

from app.database import Base


class Empresa(Base):
    __table_args__ = {"schema": "petalops"}
    __tablename__ = "empresa"

    # Mantener nombre de atributo legacy.
    idEmpresa = Column("id_empresa", BigInteger, primary_key=True, index=True)
