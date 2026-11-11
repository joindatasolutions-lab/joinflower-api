# Blueprint PetalOps

## Proposito

Este documento es la fuente general de arquitectura y trazabilidad de PetalOps.
Debe actualizarse cuando un cambio modifique contratos entre frontend, backend,
base de datos, servicios externos o reglas compartidas por los tenants.

No reemplaza la documentacion tecnica detallada de cada componente. Enlaza esos
documentos y registra las decisiones que afectan al sistema completo.

## Repositorios

| Componente | Ruta local | Rama base | Responsabilidad |
| --- | --- | --- | --- |
| Backend principal | `nuevoPetalops/joinflower-api-main/joinflower-api-main` | `main` | API operativa, autenticacion, pedidos, produccion, domicilios, inventario y administracion |
| Frontend | `Petalops_Modulos-main/Petalops_Modulos-main` | `main` | Interfaz web multitenant de PetalOps |
| Notificaciones | `nuevoPetalops/petalops-notifications` | `main` | Procesamiento desacoplado de notificaciones, idempotencia, auditoria y reintentos |

## Documentos Relacionados

- Esquema y diccionario del backend: `agent/SCHEMA.md` y `SCHEMA.md`.
- Blueprint especializado de notificaciones:
  `../../petalops-notifications/docs/blueprint-notificacion.md`.
- Migraciones y ajustes controlados de base de datos: `sql/`.

## Principios Del Sistema

1. Toda consulta y escritura de negocio debe estar aislada por `empresa_id`.
2. Las opciones propias de un tenant deben provenir de base de datos o de una
   configuracion por empresa; no deben quedar quemadas en frontend o backend.
3. Antes de crear tablas, columnas, endpoints o componentes se debe comprobar
   que no exista una funcion equivalente.
4. Los cambios de base de datos deben ser compatibles, reversibles cuando sea
   posible y seguros para tenants que aun no usen la nueva funcionalidad.
5. Los procesos externos o lentos no deben bloquear pedidos, produccion,
   domicilios ni inventario.
6. Las operaciones reintentables deben usar idempotencia y conservar auditoria.
7. Las interfaces deben conservar el sistema visual existente y funcionar en
   escritorio, tableta y movil.
8. Ningun despliegue se considera terminado sin verificar frontend, backend y,
   cuando aplique, la migracion o configuracion asociada.

## Limites De Responsabilidad

### Backend Principal

- Es la fuente de verdad de las reglas operativas.
- Valida tenant, permisos y transiciones de estado.
- Expone contratos consumidos por el frontend y otros servicios.
- No debe incorporar opciones exclusivas de una empresa mediante constantes.

### Frontend

- Consume los contratos del backend sin reconstruir reglas sensibles.
- Mantiene seleccion y sesion de empresa sin mezclar datos entre tenants.
- Presenta estados de carga y error sin ocultar fallos operativos.

### Notificaciones

- Debe permanecer desacoplado del flujo principal.
- Usa idempotencia por empresa, pedido, canal y tipo de notificacion.
- Conserva configuracion por tenant y auditoria por intento.
- La migracion de canales se realiza por fases y con un unico worker activo.

## Linea Base

Estado verificado el 2026-10-27:

| Componente | Commit sincronizado con `origin/main` | Estado |
| --- | --- | --- |
| Backend principal | `ae0e91b` | Actualizado |
| Frontend | `9277007` | Actualizado |

La linea base incluye el aislamiento de metodos de pago por tenant en backend y
frontend, y el acceso de administradores de empresa a las acciones de gestion
habilitadas por sus permisos.

## Registro De Cambios

| Fecha | Alcance | Backend | Frontend | Base de datos | Verificacion |
| --- | --- | --- | --- | --- | --- |
| 2026-10-27 | Sincronizacion inicial y creacion del blueprint general | `ae0e91b` | `9277007` | Sin cambios | Ambos repositorios coinciden con `origin/main` |
| 2026-10-27 | Costos por paquete y precios publicos de Flores | Pendiente de commit | Pendiente de commit | `inventario.costo_paquete`, `insumo.precio_venta_paquete` | Migracion aplicada; pruebas de backend y frontend correctas |
| 2026-10-27 | Arqueo fisico y control de diferencias de caja | Pendiente de commit | Pendiente de commit | `caja.total_contado`, `caja.sobrante`, `caja.faltante` | Migracion aplicada; 250 cierres historicos conservados y prueba transaccional con rollback correcta |
| 2026-10-27 | Gastos detallados y caja menor | Pendiente de commit | Pendiente de commit | `caja_gasto`; consolidado en `caja.gasto` | 117 gastos historicos migrados; suma detallada y consolidada sin diferencias |
| 2026-11-06 | Edicion de datos del cliente desde el detalle de Pedidos | `6f53f3d` | `2d04570` | Sin cambios | Usuarios con el modulo `pedidos` pueden editar nombre y telefono; usuarios sin el modulo permanecen bloqueados |
| 2026-11-06 | Cancelacion de pedidos por usuarios del modulo Pedidos | Sin cambio funcional | `4e71fea` | Sin cambios | Cancelacion habilitada para `CREADO`, `PENDIENTE` y `APROBADO`; estados finales y usuarios sin Pedidos permanecen bloqueados |
| 2026-11-06 | Catalogos y proveedores de Inventario | Mismo commit | `eaa2374` | Sin cambios | Canasto corregido; colores ampliados; edicion, busqueda y vista compacta de proveedores corregidas |
| 2026-11-11 | Edicion y eliminacion de gastos de Caja | `c1e8087` | `b63c2bb` | Sin cambios | Operaciones aisladas por tenant/sucursal y recalculo transaccional de caja |
| 2026-11-11 | Cierre de Caja sin arqueo fisico | `1244a0d` | `bb7e4db` | Sin cambios | Conserva `total_contado` en `NULL`, persiste caja menor y calcula nueva base con el efectivo esperado |
| 2026-11-11 | Importacion masiva de Inventario desde Excel | `ed25a18` | `10dfe68` | Sin cambios | Columnas flexibles, vista previa, control de duplicados y proveedores por tenant |

## Pedidos: Edicion De Datos Del Cliente

La edicion de nombre y telefono del cliente dentro del panel de detalle de un
pedido se habilita para administradores, superadministradores y usuarios que
tengan asignado el modulo `pedidos`. Esta regla no concede permisos en el
modulo independiente de Clientes ni altera los permisos de otros modulos.

El frontend valida que `pedidos` este activo en `modulosActivosPlan` y que el
usuario tenga permiso de visualizacion o edicion sobre ese modulo. El backend
mantiene la proteccion del endpoint `PUT /pedido/{pedido_id}/detalle` mediante
`require_module_access("pedidos", "puedeEditar")`, valida `empresa_id` desde la
sesion y actualiza exclusivamente el cliente vinculado al pedido del tenant.

No requiere migraciones ni cambios de datos. Los usuarios con una sesion ya
abierta deben recargar la aplicacion para obtener la version nueva del frontend.

La misma asignacion del modulo `pedidos` habilita la accion Cancelar para
pedidos en estado `CREADO`, `PENDIENTE` o `APROBADO`. La API conserva la
validacion de permisos, tenant, transicion de estado, motivo obligatorio,
auditoria y sincronizacion operativa. No se permite cancelar desde la interfaz
un pedido ya entregado, rechazado o cancelado.

## Inventario: Costos Y Precios

Modelo vigente desde el 2026-10-27:

| Concepto | Campo | Alcance |
| --- | --- | --- |
| Costo por unidad | `inventario.valor_unitario` | Todas las categorias |
| Costo por paquete | `inventario.costo_paquete` | Todas las categorias |
| Precio de venta por unidad | `insumo.precio_venta` | Flores y usos comerciales existentes, como Adicionales |
| Precio de venta por paquete | `insumo.precio_venta_paquete` | Flores |

Los campos de paquete son anulables para conservar la compatibilidad con los
registros existentes. No se crean precios implicitos ni se recalcula un valor a
partir del otro. La interfaz limita el precio de venta por paquete a Flores y el
backend normaliza ese valor a `NULL` para las demas categorias.

## Inventario: Catalogos Y Proveedores

El catalogo de Bases usa `Canasto` como subcategoria. El selector de color
incluye Gris, Terracota, Rojo oscuro, Verde claro, Fucsia, Verde esmeralda,
Mamon, Vino tinto, Mango y Bicolor, ademas de los valores existentes. No se
crearon tablas ni columnas nuevas: estos valores forman parte del catalogo
operativo del modulo y el color se sigue almacenando en `insumo.color`.

La gestion de proveedores conserva los endpoints existentes y el aislamiento
por `empresaID`:

- `GET /inventario/proveedores` lista y permite buscar por nombre, codigo,
  telefono, correo o direccion;
- `POST /inventario/proveedores` guarda todos los datos del formulario;
- `PUT /inventario/proveedores/{proveedor_id}` actualiza todos los datos y
  exige permiso de edicion de Inventario.

El frontend filtra la tabla de proveedores con el buscador general sin reducir
la lista utilizada por los selectores de otras categorias. La tabla y el modal
usan estilos compactos y mantienen una columna en pantallas pequenas.

## Inventario: Importacion Desde Excel

Las categorias Flores, Bases, Materiales y Adicionales permiten importar desde
el menu `Acciones` usando archivos `.xlsx` o `.xls`. La categoria de destino es
el submenu activo; no se confia en una categoria escrita dentro del archivo.

El lector reconoce encabezados aunque cambien mayusculas, minusculas, tildes,
espacios o variantes conocidas como `PROVEDOR`. Los campos se mapean a las
columnas existentes de `insumo` e `inventario`; no se crean tablas ni columnas.
Antes de guardar se muestra una vista previa y se separan filas invalidas.

El endpoint `POST /inventario/importar` exige permiso `puedeCrear`, valida el
`empresaID` autenticado y usa la sucursal de la sesion. Los codigos se comparan
sin distinguir mayusculas, tildes o separadores. Codigos repetidos dentro del
archivo o existentes en el tenant se omiten y se reportan por fila. Los
proveedores se reutilizan por nombre normalizado y, cuando no existen, se crean
para el mismo tenant. La carga valida todo el lote y realiza una unica
transaccion para evitar inventarios parciales por fallos tecnicos.

## Contabilidad: Arqueo De Caja

El cierre separa el dinero esperado del dinero fisicamente contado:

- efectivo esperado: `base + ventas en efectivo - gastos`;
- sobrante: `max(total contado - efectivo esperado, 0)`;
- faltante: `max(efectivo esperado - total contado, 0)`;
- nueva base con arqueo: `total contado - guardado`;
- nueva base sin arqueo: `efectivo esperado - guardado`.

El backend recalcula todos los valores derivados y rechaza gastos superiores al
efectivo disponible o montos guardados superiores al efectivo disponible para
el cierre. Cuando no se realiza arqueo, `total_contado` permanece en `NULL`,
sobrante y faltante quedan en cero, y la caja menor se persiste sin inventar un
conteo fisico. Un faltante
se registra como diferencia de arqueo y nunca se propaga como base negativa del
dia siguiente. Los cierres anteriores conservan `total_contado` en `NULL` para
no inventar arqueos historicos. La especificacion completa esta en
`docs/base_caja_req.md` y la migracion en
`sql/alter_contabilidad_caja_arqueo.sql`.

Los gastos pagados en efectivo se registran en `petalops.caja_gasto`, aislados
por empresa y sucursal. Su creacion, edicion o eliminacion recalcula dentro de
la misma transaccion el total de gastos, efectivo esperado, diferencias y nueva
base. Los contratos vigentes son `POST /contabilidad/caja/gastos`,
`PUT /contabilidad/caja/gastos/{gasto_id}` y
`DELETE /contabilidad/caja/gastos/{gasto_id}`. Las mutaciones exigen permiso de
edicion de Contabilidad y no permiten mover un gasto a otra fecha, empresa o
sucursal. El nombre visible
`Caja menor` conserva internamente la columna `caja.guardado` para mantener
compatibilidad con cierres y contratos anteriores. La migracion se encuentra en
`sql/alter_contabilidad_caja_gastos.sql`.

## Regla De Actualizacion

Para cada cambio transversal se debe registrar:

- objetivo y tenants afectados;
- contratos o endpoints modificados;
- tablas, columnas o migraciones involucradas;
- commits de backend y frontend;
- pruebas ejecutadas y resultado;
- estado de despliegue y cualquier pendiente conocido.

No se deben registrar secretos, tokens, contrasenas ni datos personales en este
documento.
