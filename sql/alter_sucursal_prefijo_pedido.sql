-- ============================================================
-- Sucursal: prefijo visible para codigo de pedido
--
-- Objetivo:
-- - Definir prefijo por sucursal para construir codigoPedido (ej: FLN-1001).
-- - Backfill de codigoPedido historico en Pedido usando numeroPedido.
-- ============================================================

START TRANSACTION;

-- 1) Prefijo configurable por sucursal
ALTER TABLE Sucursal
  ADD COLUMN IF NOT EXISTS prefijoPedido VARCHAR(12) NULL COMMENT 'Prefijo visible para codigo de pedido por sucursal';

-- 2) Backfill de prefijo para sucursales existentes (si esta vacio)
UPDATE Sucursal
SET prefijoPedido = UPPER(LEFT(REPLACE(COALESCE(nombreSucursal, 'SUC'), ' ', ''), 6))
WHERE prefijoPedido IS NULL OR TRIM(prefijoPedido) = '';

-- 3) Normalizacion del prefijo
UPDATE Sucursal
SET prefijoPedido = UPPER(TRIM(prefijoPedido))
WHERE prefijoPedido IS NOT NULL;

-- 4) Backfill de codigoPedido historico usando prefijo + numeroPedido
UPDATE Pedido p
JOIN Sucursal s ON s.idSucursal = p.sucursalID
SET p.codigoPedido = CONCAT(
  COALESCE(NULLIF(TRIM(s.prefijoPedido), ''), 'SUC'),
  '-',
  p.numeroPedido
)
WHERE p.codigoPedido IS NULL OR TRIM(p.codigoPedido) = '';

COMMIT;
