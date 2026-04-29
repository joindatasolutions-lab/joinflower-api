from sqlalchemy import Column, BigInteger, String, Date, DateTime, ForeignKey, Text
from app.database import Base


class Produccion(Base):
    __tablename__ = "produccion"
    __table_args__ = {"schema": "petalops"}

    idProduccion = Column("id_produccion", BigInteger, primary_key=True, index=True)
    empresaID = Column("empresa_id", BigInteger, nullable=False, index=True)
    sucursalID = Column("sucursal_id", BigInteger, nullable=False, index=True)
    pedidoID = Column("pedido_id", BigInteger, ForeignKey("petalops.pedido.id_pedido"), nullable=False, index=True)
    pedidoDetalleID = Column(
        "pedido_detalle_id",
        BigInteger,
        ForeignKey("petalops.pedido_detalle.id_pedido_detalle"),
        nullable=True,
        index=True,
    )
    floristaID = Column("empleado_id", BigInteger, nullable=True, index=True)
    fechaProgramadaProduccion = Column("fecha_programada_produccion", Date, nullable=False, index=True)
    fechaAsignacion = Column("fecha_asignacion", DateTime)
    fechaInicio = Column("fecha_inicio", DateTime)
    fechaFinalizacion = Column("fecha_finalizacion", DateTime)
    tiempoEstimadoMin = Column("tiempoestimadomin", BigInteger)
    tiempoRealMin = Column("tiempo_real_min", BigInteger)
    estado = Column("estado_produccion_id", BigInteger, nullable=False, index=True)
    prioridad = Column("prioridad", String(20), nullable=False, default="MEDIA")
    observacionesInternas = Column("observacionesinternas", Text)
    ordenProduccion = Column("orden_produccion", BigInteger)
    createdAt = Column("created_at", DateTime)
    updatedAt = Column("updated_at", DateTime)
