-- Seed rapido de 6 domiciliarios demo por sucursal
-- Idempotente: no duplica por (empresaID, sucursalID, nombre)
-- Requiere tabla Domiciliario creada (sql/alter_domicilios_module.sql)

INSERT INTO Domiciliario (
  empresaID,
  sucursalID,
  nombre,
  telefono,
  activo,
  createdAt,
  updatedAt
)
SELECT
  combos.empresaID,
  combos.sucursalID,
  plantilla.nombre,
  plantilla.telefono,
  1 AS activo,
  NOW() AS createdAt,
  NOW() AS updatedAt
FROM (
  SELECT DISTINCT empresaID, sucursalID FROM Pedido
  UNION
  SELECT DISTINCT empresaID, sucursalID FROM Produccion
  UNION
  SELECT DISTINCT idEmpresa AS empresaID, 1 AS sucursalID FROM Empresa
) AS combos
CROSS JOIN (
  SELECT 'Domi Demo 01' AS nombre, '3000000001' AS telefono
  UNION ALL SELECT 'Domi Demo 02', '3000000002'
  UNION ALL SELECT 'Domi Demo 03', '3000000003'
  UNION ALL SELECT 'Domi Demo 04', '3000000004'
  UNION ALL SELECT 'Domi Demo 05', '3000000005'
  UNION ALL SELECT 'Domi Demo 06', '3000000006'
) AS plantilla
LEFT JOIN Domiciliario d
  ON d.empresaID = combos.empresaID
 AND d.sucursalID = combos.sucursalID
 AND d.nombre = plantilla.nombre
WHERE d.idDomiciliario IS NULL;

-- Verificacion rapida
SELECT empresaID, sucursalID, COUNT(*) AS totalDomiciliarios
FROM Domiciliario
GROUP BY empresaID, sucursalID
ORDER BY empresaID, sucursalID;
