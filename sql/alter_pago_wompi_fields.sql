ALTER TABLE Pago
  ADD COLUMN proveedor VARCHAR(50) NOT NULL DEFAULT 'WOMPI' AFTER pedidoID,
  ADD COLUMN referencia VARCHAR(120) NULL AFTER proveedor,
  ADD COLUMN transaccionID VARCHAR(120) NULL AFTER referencia,
  ADD COLUMN estado VARCHAR(40) NOT NULL DEFAULT 'PENDIENTE' AFTER transaccionID,
  ADD COLUMN moneda VARCHAR(10) NOT NULL DEFAULT 'COP' AFTER estado,
  ADD COLUMN checkoutUrl TEXT NULL AFTER monto,
  ADD COLUMN rawRespuesta TEXT NULL AFTER checkoutUrl;

CREATE UNIQUE INDEX uq_pago_referencia ON Pago (referencia);

UPDATE Pago
SET proveedor = IFNULL(NULLIF(metodoPago, ''), 'WOMPI')
WHERE proveedor IS NULL OR proveedor = '';

UPDATE Pago
SET referencia = CONCAT('legacy_', idPago)
WHERE referencia IS NULL OR referencia = '';
