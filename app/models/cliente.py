from sqlalchemy import Column, BigInteger, String, Boolean, DateTime, ForeignKey
from app.database import Base

class Cliente(Base):
    __tablename__ = "cliente"
    __table_args__ = {"schema": "petalops"}

    idCliente = Column("cliente_id", BigInteger, primary_key=True, index=True)
    empresaID = Column("empresa_id", BigInteger, ForeignKey("petalops.empresa.id_empresa"))
    tipoIdent = Column("tipo_ident", String(30))
    identificacion = Column("identificacion", String(50))
    indicativo = Column("indicativo", String(10))
    telefonoCompleto = Column("telefono_completo", String(40))
    nombreCompleto = Column("nombre_completo", String(150))
    telefono = Column("telefono", String(30))
    email = Column("email", String(150))
    activo = Column("activo", Boolean)
    createdAt = Column("created_at", DateTime)
    updatedAt = Column("updated_at", DateTime)
