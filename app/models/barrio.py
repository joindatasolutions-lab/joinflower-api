from sqlalchemy import Column, BigInteger, String, Numeric, DateTime, ForeignKey

from app.database import Base


class Barrio(Base):
    __tablename__ = "barrio"
    __table_args__ = {"schema": "petalops"}

    idBarrio = Column("id_barrio", BigInteger, primary_key=True, index=True)
    empresaID = Column("empresa_id", BigInteger, ForeignKey("petalops.empresa.id_empresa"), nullable=False)
    sucursalID = Column("sucursal_id", BigInteger, ForeignKey("petalops.sucursal.id_sucursal"))
    zonaID = Column("zona_id", BigInteger, nullable=False)
    nombreBarrio = Column("nombre_barrio", String(150), nullable=False)
    costoDomicilio = Column("costo_domicilio", Numeric(12, 2), nullable=False)
    activo = Column("activo", BigInteger, nullable=False)
    createdAt = Column("created_at", DateTime)
    updatedAt = Column("updated_at", DateTime)
