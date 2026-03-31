from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, String

from app.database import Base


class Proveedor(Base):
    __tablename__ = "proveedor"
    __table_args__ = {"schema": "petalops"}

    idProveedor = Column("id_proveedor", BigInteger, primary_key=True, index=True)
    # Nota: en esquema actual proveedor es tabla global (sin empresa_id).
    empresaID = Column("empresa_id", BigInteger, nullable=True, index=True)
    nombreProveedor = Column("nombre_proveedor", String(150), nullable=False)
    codigoProveedor = Column("codigo_proveedor", String(80), nullable=True)
    activo = Column(Boolean, nullable=False, default=True)
    createdAt = Column("created_at", DateTime)
    updatedAt = Column("updated_at", DateTime)
