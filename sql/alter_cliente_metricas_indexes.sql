-- Indices recomendados para metricas de clientes.
-- Ejecutar en una ventana controlada si la tabla pedido/pedido_detalle tiene alto volumen.

CREATE INDEX IF NOT EXISTS idx_cliente_empresa_id
  ON petalops.cliente (empresa_id, cliente_id);

CREATE INDEX IF NOT EXISTS idx_pedido_empresa_cliente_fecha_estado
  ON petalops.pedido (empresa_id, cliente_id, fecha_pedido, estado_pedido_id);

CREATE INDEX IF NOT EXISTS idx_pedido_detalle_empresa_pedido_producto
  ON petalops.pedido_detalle (empresa_id, pedido_id, producto_id);

CREATE INDEX IF NOT EXISTS idx_pedido_canal_venta_empresa_pedido
  ON petalops.pedido_canal_venta (empresa_id, pedido_id);

CREATE INDEX IF NOT EXISTS idx_producto_empresa_categoria
  ON petalops.producto (empresa_id, categoria_id, id_producto);
