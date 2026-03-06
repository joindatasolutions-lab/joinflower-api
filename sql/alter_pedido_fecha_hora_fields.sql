ALTER TABLE Pedido
  ADD COLUMN IF NOT EXISTS fechaPedidoDate DATE NULL AFTER fechaPedido,
  ADD COLUMN IF NOT EXISTS horaPedido TIME NULL AFTER fechaPedidoDate;

UPDATE Pedido
SET
  fechaPedidoDate = DATE(fechaPedido),
  horaPedido = TIME(fechaPedido)
WHERE fechaPedido IS NOT NULL
  AND (fechaPedidoDate IS NULL OR horaPedido IS NULL);
