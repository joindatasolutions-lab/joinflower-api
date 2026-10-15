# Indicadores y consultas auxiliares de pedidos

`ventaHoy` y `pedidosHoy` usan `fecha_pedido` en hora de Colombia: desde las 00:00 incluidas hasta las 00:00 del d?a siguiente excluidas. Se intersectan con los filtros del listado, incluso al buscar; no dependen de la p?gina. Un rango hist?rico sin pedidos de hoy devuelve cero en ambos indicadores.

Se conserva la clasificaci?n comercial: `pedidosHoy` cuenta CREADO, PENDIENTE, APROBADO y PAGADO; `ventaHoy` suma total_bruto + total_iva de APROBADO y PAGADO, tratando valores nulos como cero. Los contadores aprobados, pendientes, cancelados y sinImprimir abarcan todos los candidatos filtrados. Como antes, sinImprimir restringe las filas y el total de paginaci?n, pero no los dem?s indicadores.

Las estad?sticas se resuelven mediante una sola agregaci?n SQL sobre los IDs distintos de los candidatos. La aprobaci?n con pagos mixtos reutiliza el total del pedido cargado para la p?gina.

## Despliegue

Ejecutar `sql/create_pedido_auxiliary_tables.sql` con el usuario de migraciones antes de desplegar esta versi?n. Es idempotente y crea las tablas e ?ndices de auditor?a y alertas de voz previamente creados durante solicitudes. Los endpoints ahora requieren esas tablas existentes y no ejecutan DDL. No se elimina informaci?n ni se modifica el esquema autom?ticamente al atender solicitudes.
