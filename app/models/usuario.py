from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, String

from app.database import Base


class Usuario(Base):
    __tablename__ = "usuario"
    __table_args__ = {"schema": "petalops"}

    # Mantener nombres de atributos legacy en Python para no romper routers/servicios.
    idusuario = Column("id_usuario", BigInteger, primary_key=True, index=True)
    empresaID = Column("empresa_id", BigInteger, ForeignKey("petalops.empresa.id_empresa"), nullable=True, index=True)
    sucursalID = Column("sucursal_id", BigInteger, nullable=True, index=True)
    nombre = Column("nombre", String(150), nullable=False)
    login = Column("login", String(80), nullable=False, unique=True, index=True)
    email = Column("email", String(180), nullable=False)
    passwordHash = Column("passwordhash", String(255), nullable=False)
    rolID = Column("rolid", BigInteger, ForeignKey("petalops.rol.id_rol"), nullable=True, index=True)
    estado = Column("estado", String(20), nullable=False, default="activo")
    esSuperadmin = Column("es_superadmin", Boolean, nullable=False, default=False)
    ultimoLogin = Column("ultimo_login", DateTime)
    createdAt = Column("created_at", DateTime)
    updatedAt = Column("updated_at", DateTime)
