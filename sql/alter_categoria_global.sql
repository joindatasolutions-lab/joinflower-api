-- Script de alteración y limpieza de la tabla categoria para modelo SaaS global
-- 1. Eliminar duplicados y limpiar datos en categoria
-- 2. Crear índice UNIQUE global (nombreCategoria, empresaID IS NULL)
-- 3. Actualizar FK en Producto, PedidoDetalle y CatalogoArreglos

USE joindata_app;

-- 1. Eliminar duplicados (mantener el de menor idCategoria)
DELETE c1 FROM Categoria c1
INNER JOIN Categoria c2
  ON c1.nombreCategoria = c2.nombreCategoria
 AND IFNULL(c1.empresaID, 0) = IFNULL(c2.empresaID, 0)
 AND c1.idCategoria > c2.idCategoria;

-- 2. Limpiar espacios y normalizar nombres
UPDATE Categoria SET nombreCategoria = TRIM(nombreCategoria);

-- 3. Hacer global las categorías (empresaID = NULL)
UPDATE Categoria SET empresaID = NULL;

-- 4. Crear índice UNIQUE global
ALTER TABLE Categoria
  ADD UNIQUE KEY uq_nombreCategoria_global (nombreCategoria);

-- 5. Actualizar FK en Producto
UPDATE Producto p
JOIN Categoria c ON p.categoriaID = c.idCategoria
   AND p.empresaID = 3 -- Ajustar si es necesario
SET p.categoriaID = c.idCategoria;

-- 6. Actualizar FK en PedidoDetalle
UPDATE PedidoDetalle pd
JOIN Producto p ON pd.productoID = p.idProducto
SET pd.categoriaID = p.categoriaID
WHERE pd.categoriaID IS NULL;

-- 7. Actualizar FK en CatalogoArreglos (si aplica)
-- UPDATE CatalogoArreglos ca
-- JOIN Categoria c ON ca.nombreCategoria = c.nombreCategoria
-- SET ca.categoriaID = c.idCategoria
-- WHERE ca.categoriaID IS NULL;

-- 8. Validar integridad referencial
-- (Opcional: agregar restricciones FK si no existen)
-- ALTER TABLE Producto ADD CONSTRAINT fk_producto_categoria FOREIGN KEY (categoriaID) REFERENCES Categoria(idCategoria);
-- ALTER TABLE PedidoDetalle ADD CONSTRAINT fk_pedidodetalle_categoria FOREIGN KEY (categoriaID) REFERENCES Categoria(idCategoria);
-- ALTER TABLE CatalogoArreglos ADD CONSTRAINT fk_catalogoarreglos_categoria FOREIGN KEY (categoriaID) REFERENCES Categoria(idCategoria);

-- 9. Reporte de categorías afectadas
SELECT * FROM Categoria ORDER BY nombreCategoria;