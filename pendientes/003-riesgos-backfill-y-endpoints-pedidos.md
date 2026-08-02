# Pendiente 003 - Riesgos si no se ejecutan backfills y limpieza de endpoints

## Pendientes

1. Revisar/backfill de pedidos aprobados sin produccion.
2. Revisar/backfill de pedidos sin auditoria historica.
3. Definir si `POST /pedido` se depreca formalmente y dejar `POST /pedido/manual` como endpoint oficial de backoffice.

## Riesgo si no se hace antes de produccion

### Pedidos aprobados sin produccion
Si existen pedidos validos aprobados sin registros en `produccion`, el modulo de produccion puede no mostrar trabajo pendiente para esos pedidos. Esto puede causar pedidos aprobados que comercialmente existen, pero operativamente no entran al tablero de floristas.

### Pedidos sin auditoria historica
Si existen pedidos sin `pedido_auditoria`, no se puede reconstruir quien los creo, aprobo o cancelo. Para soporte, reclamos, contabilidad o trazabilidad, esos pedidos quedaran con historial incompleto.

### Endpoint legado `POST /pedido`
Si el front o algun cliente externo sigue usando `POST /pedido`, puede haber comportamientos diferentes frente a `POST /pedido/manual`: payload distinto, respuesta distinta y logica menos completa. Conviene confirmar uso real antes de quitarlo; si no se usa, marcarlo como legado/deprecado.

## Recomendacion
No ejecutar backfills a ciegas. Primero sacar conteos y muestras por empresa, validar con negocio, y luego ejecutar scripts idempotentes con `WHERE NOT EXISTS`.