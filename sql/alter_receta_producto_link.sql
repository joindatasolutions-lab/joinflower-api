-- Vincula cada receta (Arreglo) a un producto vendible del catalogo, para
-- reutilizar precio/imagen de petalops.producto_sucursal en vez de duplicarlos,
-- y para poder calcular "reservados"/"vendidos hoy" a partir de pedido_detalle
-- (que solo referencia producto_id, nunca receta_id).
-- Tambien agrega un override manual opcional de capacidad de fabricacion.
ALTER TABLE petalops.receta
  ADD COLUMN IF NOT EXISTS producto_id BIGINT REFERENCES petalops.producto(id_producto),
  ADD COLUMN IF NOT EXISTS capacidad_manual NUMERIC(12,2);
