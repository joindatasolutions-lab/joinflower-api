from sqlalchemy import Boolean, Column, DateTime
from sqlalchemy.dialects.postgresql import BIGINT

from app.database import Base


class EmpresaConfiguracionAsignacion(Base):
    __tablename__ = "empresa_configuracion_asignacion"
    __table_args__ = {"schema": "petalops"}

    idConfiguracion = Column("id_configuracion", BIGINT, primary_key=True, index=True)
    empresaID = Column("empresa_id", BIGINT, nullable=False, unique=True, index=True)
    asignacionProduccionActiva = Column("asignacion_produccion_activa", Boolean, nullable=False, default=False)
    asignacionDomicilioActiva = Column("asignacion_domicilio_activa", Boolean, nullable=False, default=False)
    autoAsignacionProduccionActiva = Column("auto_asignacion_produccion_activa", Boolean, nullable=False, default=True)
    createdAt = Column("created_at", DateTime, nullable=False)
    updatedAt = Column("updated_at", DateTime, nullable=False)
