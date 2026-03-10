-- Restaura precios activos desde respaldo (si existe)
START TRANSACTION;

UPDATE Producto p
INNER JOIN Producto_precio_backup b ON b.idProducto = p.idProducto
SET p.precio = b.precio_original
WHERE p.activo = 1;

COMMIT;

SELECT ROW_COUNT() AS filas_restauradas;
SELECT idProducto, nombreProducto, precio
FROM Producto
WHERE activo = 1
ORDER BY idProducto;
