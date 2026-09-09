from sqlalchemy import Boolean, Column, DateTime, String
from sqlalchemy.dialects.postgresql import BIGINT

from app.database import Base


class Tema(Base):
    __tablename__ = "tema"
    __table_args__ = {"schema": "petalops"}

    idTema = Column("id_tema", BIGINT, primary_key=True, index=True)
    empresaID = Column("empresa_id", BIGINT, nullable=False, index=True)
    colorPrimario = Column("color_primario", String(20))
    colorSecundario = Column("color_secundario", String(20))
    colorFondo = Column("color_fondo", String(20))
    colorFondoSuave = Column("color_fondo_suave", String(20))
    colorTexto = Column("color_texto", String(20))
    colorTextoSuave = Column("color_texto_suave", String(20))
    colorBorde = Column("color_borde", String(20))
    fuenteFamilia = Column("fuente_familia", String(255))
    fuenteTamanoBase = Column("fuente_tamano_base", String(20))
    activo = Column("activo", Boolean, nullable=False, default=True)
    createdAt = Column("created_at", DateTime)
    updatedAt = Column("updated_at", DateTime)
