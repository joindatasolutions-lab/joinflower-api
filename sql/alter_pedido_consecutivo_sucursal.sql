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
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='pedido' AND column_name='numeropedido') THEN
    ALTER TABLE "Pedido" ADD COLUMN numeroPedido BIGINT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='pedido' AND column_name='codigopedido') THEN
    ALTER TABLE "Pedido" ADD COLUMN codigoPedido VARCHAR(40);
  END IF;
END$$;

-- 2) Backfill para filas existentes:
--    Genera consecutivo por empresa/sucursal para poder marcar numeroPedido como NOT NULL.
WITH numerados AS (
  SELECT idPedido, ROW_NUMBER() OVER (PARTITION BY "empresaID", "sucursalID" ORDER BY "idPedido") AS nuevoNumero
  FROM "Pedido"
)
UPDATE "Pedido" p
SET numeroPedido = n.nuevoNumero
FROM numerados n
WHERE n.idPedido = p.idPedido AND p.numeroPedido IS NULL;

-- 3) Dejar numeroPedido NOT NULL (requisito funcional)
ALTER TABLE "Pedido" ALTER COLUMN numeroPedido SET NOT NULL;

-- 4) Restriccion unica por empresa + sucursal + consecutivo
ALTER TABLE "Pedido" ADD CONSTRAINT uq_pedido_empresa_sucursal_numero UNIQUE ("empresaID", "sucursalID", numeroPedido);

-- 5) Tabla de contador por sucursal para asignacion atomica de consecutivos
CREATE TABLE IF NOT EXISTS "SucursalContadorPedido" (
  "empresaID" BIGINT NOT NULL,
  "sucursalID" BIGINT NOT NULL,
  "ultimoPedido" BIGINT NOT NULL,
  "updatedAt" TIMESTAMP,
  PRIMARY KEY ("empresaID", "sucursalID"),
  CONSTRAINT fk_scp_empresa FOREIGN KEY ("empresaID") REFERENCES "Empresa"("idEmpresa"),
  CONSTRAINT fk_scp_sucursal FOREIGN KEY ("sucursalID") REFERENCES "Sucursal"("idSucursal")
);

-- 6) Inicializar contador con el maximo actual por sucursal
INSERT INTO "SucursalContadorPedido" ("empresaID", "sucursalID", "ultimoPedido", "updatedAt")
SELECT
  p."empresaID",
  p."sucursalID",
  MAX(p.numeroPedido) AS ultimoPedido,
  CURRENT_TIMESTAMP AS "updatedAt"
FROM "Pedido" p
GROUP BY p.empresaID, p.sucursalID
ON DUPLICATE KEY UPDATE
  ultimoPedido = VALUES(ultimoPedido),
  updatedAt = VALUES(updatedAt);

COMMIT;
