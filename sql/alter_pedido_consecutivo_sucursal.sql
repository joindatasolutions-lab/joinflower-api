-- ============================================================
-- Pedido: consecutivo visible por sucursal (MySQL 8)
--
-- Arquitectura:
-- - idPedido sigue siendo el identificador tecnico global.
-- - numeroPedido es el consecutivo por (empresaID, sucursalID).
-- - codigoPedido es el identificador visible para clientes.
-- - SucursalContadorPedido evita colisiones por concurrencia.
-- ============================================================

START TRANSACTION;

-- 1) Agregar nuevas columnas en Pedido
ALTER TABLE Pedido
  ADD COLUMN IF NOT EXISTS numeroPedido BIGINT NULL COMMENT 'Consecutivo por sucursal; idPedido es la llave tecnica global',
  ADD COLUMN IF NOT EXISTS codigoPedido VARCHAR(40) NULL COMMENT 'Identificador visible para cliente (ej: FLN-1001)';

-- 2) Backfill para filas existentes:
--    Genera consecutivo por empresa/sucursal para poder marcar numeroPedido como NOT NULL.
UPDATE Pedido p
JOIN (
  SELECT
    idPedido,
    ROW_NUMBER() OVER (
      PARTITION BY empresaID, sucursalID
      ORDER BY idPedido
    ) AS nuevoNumero
  FROM Pedido
) x ON x.idPedido = p.idPedido
SET p.numeroPedido = x.nuevoNumero
WHERE p.numeroPedido IS NULL;

-- 3) Dejar numeroPedido NOT NULL (requisito funcional)
ALTER TABLE Pedido
  MODIFY COLUMN numeroPedido BIGINT NOT NULL COMMENT 'Consecutivo de pedido por sucursal; no reemplaza idPedido tecnico global';

-- 4) Restriccion unica por empresa + sucursal + consecutivo
ALTER TABLE Pedido
  ADD CONSTRAINT uq_pedido_empresa_sucursal_numero
  UNIQUE (empresaID, sucursalID, numeroPedido);

-- 5) Tabla de contador por sucursal para asignacion atomica de consecutivos
CREATE TABLE IF NOT EXISTS SucursalContadorPedido (
  empresaID BIGINT NOT NULL,
  sucursalID BIGINT NOT NULL,
  ultimoPedido BIGINT NOT NULL COMMENT 'Ultimo consecutivo asignado para la sucursal',
  updatedAt DATETIME NULL,
  PRIMARY KEY (empresaID, sucursalID),
  CONSTRAINT fk_scp_empresa FOREIGN KEY (empresaID) REFERENCES Empresa(idEmpresa),
  CONSTRAINT fk_scp_sucursal FOREIGN KEY (sucursalID) REFERENCES Sucursal(idSucursal)
) ENGINE=InnoDB COMMENT='Control de consecutivo de pedidos por sucursal';

-- 6) Inicializar contador con el maximo actual por sucursal
INSERT INTO SucursalContadorPedido (empresaID, sucursalID, ultimoPedido, updatedAt)
SELECT
  p.empresaID,
  p.sucursalID,
  MAX(p.numeroPedido) AS ultimoPedido,
  NOW() AS updatedAt
FROM Pedido p
GROUP BY p.empresaID, p.sucursalID
ON DUPLICATE KEY UPDATE
  ultimoPedido = VALUES(ultimoPedido),
  updatedAt = VALUES(updatedAt);

COMMIT;
