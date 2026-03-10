-- Guarda un respaldo de precios activos y luego fija precio de prueba a 1500.00
START TRANSACTION;

CREATE TABLE IF NOT EXISTS Producto_precio_backup (
  idProducto BIGINT NOT NULL,
  precio_original DECIMAL(12,2) NOT NULL,
  backed_up_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (idProducto)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

REPLACE INTO Producto_precio_backup (idProducto, precio_original, backed_up_at)
SELECT p.idProducto, p.precio, NOW()
FROM Producto p
WHERE p.activo = 1;

UPDATE Producto
SET precio = 1500.00
WHERE activo = 1;

COMMIT;

SELECT ROW_COUNT() AS filas_actualizadas;
SELECT idProducto, nombreProducto, precio
FROM Producto
WHERE activo = 1
ORDER BY idProducto;
