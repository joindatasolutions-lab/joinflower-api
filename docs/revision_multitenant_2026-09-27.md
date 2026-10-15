# Correcciones multitenant ? 2026-09-27

Se completaron los pendientes identificados en consultas auxiliares y pertenencia de sucursales.

- Validaci?n compartida de sucursal/empresa en filtros operativos y altas de pedidos, barrios y cierres de caja.
- Creaci?n y actualizaci?n de usuarios: la sucursal debe pertenecer a la empresa destino.
- Numeraci?n de pedidos: eliminado el fallback que aceptaba sucursales de otra empresa.
- Pedidos, entregas, pipeline y domicilios: consultas auxiliares y cruces limitados a la empresa del registro autorizado.
- Producci?n: cantidades, entregas, floristas y producciones relacionadas filtradas por empresa.
- Inventario: excluido de esta entrega; conserva origin/main. Los cambios locales de aislamiento permanecen respaldados en un stash y su prueba queda omitida hasta retomar ese trabajo.

## Validaci?n

`python -m pytest -q`: 345 aprobadas, 14 omitidas (validacion del 2026-10-15, sin integracion remota).

Pruebas nuevas con SQLite temporal y dos empresas: rechazo de sucursales ajenas/inexistentes, rechazo antes de escritura en barrios/caja/producci?n, numeraci?n sin fallback, cantidades de producci?n y aislamiento de productos/im?genes. Las pruebas existentes con bases simuladas se adaptaron a la nueva consulta de sucursal.

Las pruebas de integraci?n contra servicios y PostgreSQL no se habilitaron. Este resultado valida las correcciones locales; no certifica el esquema desplegado, datos hist?ricos, restricciones de base de datos ni la ausencia absoluta de otras vulnerabilidades. No se desplegaron cambios ni se modificaron datos remotos.
