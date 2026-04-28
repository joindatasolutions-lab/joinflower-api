from sqlalchemy import Column, DateTime, BigInteger, Integer, String, case, func, select
from sqlalchemy.orm import column_property

from app.models.perfilflorista import PerfilFlorista
from app.database import Base


class Florista(Base):
    # Compatibilidad con esquema actual: no existe tabla florista,
    # se representa con empleados cuyo cargo es "Florista".
    __tablename__ = "empleado"
    __table_args__ = {"schema": "petalops"}

    idFlorista = Column("id_empleado", BigInteger, primary_key=True, index=True)
    empresaID = Column("empresa_id", BigInteger, nullable=False, index=True)
    sucursalID = Column("sucursal_id", BigInteger, nullable=True, index=True)
    usuarioID = Column("usuario_id", BigInteger, nullable=True, index=True)
    nombre = Column("nombre_empleado", String(150), nullable=False)
    cargo = Column("cargo", String(100), nullable=False)
    activo = Column("activo", Integer, nullable=False, default=1)
    createdAt = Column("created_at", DateTime)
    updatedAt = Column("updated_at", DateTime)

    # Campos extendidos desde perfil_florista.
    capacidadDiaria = column_property(
        select(PerfilFlorista.capacidadDiaria)
        .where(PerfilFlorista.empleadoID == idFlorista)
        .correlate_except(PerfilFlorista)
        .scalar_subquery()
    )
    trabajosSimultaneosPermitidos = column_property(
        select(PerfilFlorista.trabajosSimultaneosPermitidos)
        .where(PerfilFlorista.empleadoID == idFlorista)
        .correlate_except(PerfilFlorista)
        .scalar_subquery()
    )
    fechaInicioIncapacidad = column_property(
        select(PerfilFlorista.fechaInicioIncapacidad)
        .where(PerfilFlorista.empleadoID == idFlorista)
        .correlate_except(PerfilFlorista)
        .scalar_subquery()
    )
    fechaFinIncapacidad = column_property(
        select(PerfilFlorista.fechaFinIncapacidad)
        .where(PerfilFlorista.empleadoID == idFlorista)
        .correlate_except(PerfilFlorista)
        .scalar_subquery()
    )
    especialidades = column_property(
        select(PerfilFlorista.especialidades)
        .where(PerfilFlorista.empleadoID == idFlorista)
        .correlate_except(PerfilFlorista)
        .scalar_subquery()
    )
    estado = column_property(
        func.coalesce(
            select(
                case(
                    (
                        (PerfilFlorista.fechaInicioIncapacidad.is_not(None))
                        & (PerfilFlorista.fechaInicioIncapacidad <= func.now())
                        & (
                            (PerfilFlorista.fechaFinIncapacidad.is_(None))
                            | (PerfilFlorista.fechaFinIncapacidad >= func.now())
                        ),
                        "Incapacidad",
                    ),
                    else_="Activo",
                )
            )
            .where(PerfilFlorista.empleadoID == idFlorista)
            .correlate_except(PerfilFlorista)
            .scalar_subquery(),
            "Activo",
        )
    )
