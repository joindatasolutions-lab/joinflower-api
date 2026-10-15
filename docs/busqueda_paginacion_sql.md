# B?squeda y paginaci?n SQL

## Backend

- `/pedidos`: filtros y b?squeda antes de `LIMIT/OFFSET`; conteo y KPIs agregados en SQL sobre el conjunto filtrado. `sinImprimir` restringe la p?gina y el total; los KPIs conservan el conjunto base previo a esa selecci?n. Solo se enriquecen los pagos/productos de la p?gina.
- `/produccion`: `page` (1 por defecto), `pageSize` (50 por defecto, m?ximo 100), `total` del conjunto filtrado. La b?squeda comparte los campos de pedidos y a?ade el nombre del florista.
- Se conserva el comportamiento de b?squeda global: `q` no vac?o omite fecha y estado como antes; empresa/sucursal y filtros espec?ficos siguen aplicando.
- Intento vigente en pedidos, producci?n, pipeline y domicilios: `intentoNumero DESC NULLS LAST, idEntrega DESC`, dentro de empresa y pedido. Los filtros y los datos mostrados usan ese intento.
- Si existen varios pagos de un pedido, se usa el mayor `id_pago` para el estado de impresi?n, lectura y actualizaci?n de metadatos.

## Despliegue

Aplicar `sql/create_factura_impresa_function.sql` **antes** de desplegar la API. La funci?n interpreta `_petalopsMetadata.facturaImpresa` y tolera respuestas legacy no JSON. Es necesaria para filtrar sin imprimir y agregar indicadores sin descargar todos los pagos. No se ha aplicado a una base remota ni validado en PostgreSQL real.

## Frontend pendiente de acceso

El frontend no est? en este workspace. Debe enviar `q`, filtros, `page` y `pageSize` en cada petici?n; mostrar `total` del servidor; restablecer `page=1` al cambiar filtros; cancelar/ignorar respuestas de b?squedas anteriores. Eliminar bucles que recorren todas las p?ginas y filtros o paginaci?n locales. Producci?n ahora devuelve una p?gina por defecto: coordinar el despliegue con ese consumidor para que no oculte registros posteriores a la primera p?gina.

No se ha modificado el frontend. Se solicit? su ubicaci?n.
