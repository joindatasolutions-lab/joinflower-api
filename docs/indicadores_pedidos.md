# Indicadores y consultas auxiliares de pedidos

`ventaPeriodo` y `pedidosPeriodo` resumen todos los pedidos que cumplen los filtros del listado, independientemente de la fecha actual y de la pagina. Las tarjetas de ventas y pedidos del periodo deben consumir estos campos. `ventaHoy` y `pedidosHoy` conservan el calculo diario en hora de Colombia por compatibilidad.

Se conserva la clasificaci?n comercial: `pedidosHoy` cuenta CREADO, PENDIENTE, APROBADO y PAGADO; `ventaHoy` suma total_bruto + total_iva de APROBADO y PAGADO, tratando valores nulos como cero. Los contadores aprobados, pendientes, cancelados y sinImprimir abarcan todos los candidatos filtrados. `sinImprimir` se aplica antes de calcular listado, total y todos los KPI, igual que los demas filtros.

Las estad?sticas se resuelven mediante una sola agregaci?n SQL sobre los IDs distintos de los candidatos. La aprobaci?n con pagos mixtos reutiliza el total del pedido cargado para la p?gina.

## Despliegue

Ejecutar `sql/create_pedido_auxiliary_tables.sql` con el usuario de migraciones antes de desplegar esta versi?n. Es idempotente y crea las tablas e ?ndices de auditor?a y alertas de voz previamente creados durante solicitudes. Los endpoints ahora requieren esas tablas existentes y no ejecutan DDL. No se elimina informaci?n ni se modifica el esquema autom?ticamente al atender solicitudes.

## Busqueda y filtros

`GET /pedidos` combina `q` con todos los filtros recibidos mediante AND. Sin `fechaDesde` ni `fechaHasta` no se impone un rango de fechas. Con fechas, `filtrarPorEntrega=true` usa la fecha del ultimo intento de entrega; en caso contrario usa la fecha de creacion. Se admiten limites de fecha independientes. Empresa y sucursal mantienen su aislamiento. El total y los KPI se calculan antes de paginar y no cambian al pasar de pagina.
