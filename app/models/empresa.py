from sqlalchemy import Boolean, Column, BigInteger, String

from app.database import Base


class Empresa(Base):
    __table_args__ = {"schema": "petalops"}
    __tablename__ = "empresa"

    # Mantener nombre de atributo legacy.
    idEmpresa = Column("id_empresa", BigInteger, primary_key=True, index=True)
    # Nombres reales de la empresa (multi-tenant). Sin mapear, la factura y otros
    # consumidores caian al valor por defecto "FLORA" para todas las empresas.
    nombreEmpresa = Column("nombre_empresa", String(150), nullable=True)
    nombreComercial = Column("nombre_comercial", String(180), nullable=True)
    slug = Column("slug", String(50), nullable=True)
    celular = Column("celular", String(40), nullable=True)
    datosTransferenciaCatalogoActivo = Column("datos_transferencia_catalogo_activo", Boolean, nullable=False, default=False)
