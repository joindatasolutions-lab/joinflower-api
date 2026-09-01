from sqlalchemy import BigInteger, Column, Date, DateTime, ForeignKey, Numeric, String, Text

from app.database import Base


class MovimientoInventario(Base):
    __tablename__ = "movimiento_inventario"
    __table_args__ = {"schema": "petalops"}

    idMovimiento = Column("id_movimiento", BigInteger, primary_key=True, index=True)
    empresaID = Column("empresa_id", BigInteger, ForeignKey("petalops.empresa.id_empresa"), nullable=False, index=True)
    inventarioID = Column("inventario_id", BigInteger, ForeignKey("petalops.inventario.id_inventario"), nullable=False, index=True)
    tipoMovimiento = Column("tipo_movimiento_id", BigInteger, nullable=True, index=True)
    cantidad = Column(Numeric(12, 2), nullable=False)
    fecha = Column(DateTime, nullable=False, index=True)
    motivo = Column(String(250), nullable=True)
    usuarioID = Column("usuario_id", BigInteger, ForeignKey("petalops.usuario.id_usuario"), nullable=True, index=True)
    createdAt = Column("created_at", DateTime)
    estado = Column(String(20), nullable=False, default="Registrado", index=True)
    anuladoAt = Column("anulado_at", DateTime, nullable=True)
    anuladoPorUsuarioID = Column("anulado_por_usuario_id", BigInteger, ForeignKey("petalops.usuario.id_usuario"), nullable=True)
    motivoAnulacion = Column("motivo_anulacion", Text, nullable=True)
    stockAnterior = Column("stock_anterior", Numeric(12, 2), nullable=True)
    stockNuevo = Column("stock_nuevo", Numeric(12, 2), nullable=True)
    referencia = Column(String(80), nullable=True)
    proveedorID = Column("proveedor_id", BigInteger, ForeignKey("petalops.proveedor.id_proveedor"), nullable=True)
    numeroFactura = Column("numero_factura", String(80), nullable=True)
    responsable = Column(String(150), nullable=True)
    unidad = Column(String(50), nullable=True)
    precioUnitario = Column("precio_unitario", Numeric(12, 2), nullable=True)
    fechaVencimiento = Column("fecha_vencimiento", Date, nullable=True)
    evidenciaUrl = Column("evidencia_url", Text, nullable=True)
    pedidoReferencia = Column("pedido_referencia", String(80), nullable=True)
    observaciones = Column(Text, nullable=True)
    movimientoOrigenID = Column("movimiento_origen_id", BigInteger, ForeignKey("petalops.movimiento_inventario.id_movimiento"), nullable=True)
