# Contrato de concurrencia de pedidos

## Despliegue y cliente

Ejecutar `sql/create_pedido_operacion.sql` antes de desplegar. No se ejecuta DDL durante solicitudes. Coordinar el cambio del cliente: la creacion ahora exige `Idempotency-Key` (1 a 128 caracteres); editar/agregar detalle exige `version` positiva en el cuerpo; eliminar detalle exige `?version=N`. GET de listado y detalle devuelven `version` y las ediciones devuelven la nueva version.

## Creacion

POST `/pedido`, `/pedido/manual`, `/pedido/venta-rapida` y `/pedido/checkout` reservan una clave por empresa y operacion. La restriccion unica serializa solicitudes simultaneas. Una clave repetida con el mismo cuerpo devuelve la respuesta original; otro cuerpo devuelve 409 `IDEMPOTENCY_KEY_REUSED`. Un error previo al commit revierte tanto el pedido como la reserva. Si se pierde la respuesta despues del commit, el reintento recupera la respuesta guardada. Checkout incluye auditoria y respuesta idempotente en la misma transaccion.

Usar UUID generado una sola vez por accion, persistirlo antes de enviar y conservar exactamente el cuerpo de cada reintento. Una nueva accion requiere nueva clave. Las reservas no se purgan automaticamente: eliminarlas permitiria volver a crear pedidos con claves antiguas.

## Edicion

El backend bloquea el pedido con SELECT FOR UPDATE antes de comprobar version. Una version desactualizada produce 409 `PEDIDO_VERSION_CONFLICT` con `versionActual`; no aplica cambios. Las ediciones y los cambios de estado avanzan la version. Ante conflicto, volver a leer y reconciliar los cambios del usuario; no sustituir la version automaticamente.

## Duplicaciones realizadas en varios pasos

Este repositorio no contiene un endpoint de duplicacion ni el cliente que coordina ese flujo. El backend permite recuperarlo mediante claves por paso:

1. Persistir localmente el identificador de duplicacion, el cuerpo de creacion y su clave. Repetir POST manual con esa misma clave recupera el ID creado, sin otro pedido.
2. Leer el detalle para obtener su version. Antes de cada PUT/POST de detalle, persistir el cuerpo completo (incluida version) y una clave estable distinta por paso.
3. Estos endpoints de detalle aceptan `Idempotency-Key` opcional. Su resultado se guarda junto con los cambios. Repetir un paso confirmado devuelve su respuesta sin ejecutarlo ni incrementar otra vez la version. Un paso fallido se revierte y puede reintentarse con la misma clave y cuerpo.
4. Continuar desde el primer paso pendiente. Si otro usuario modifico el pedido, detenerse y reconciliar el conflicto de version. No recrear el pedido para resolverlo.

Los borrados tienen control de version, pero no replay idempotente. Los resultados de replay representan el resultado original, no el estado actual: al terminar la recuperacion, volver a leer el pedido.

No se puede vincular automaticamente una duplicacion antigua sin claves a una nueva solicitud. Una reserva incompleta confirmada por otro codigo se rechaza con `OPERATION_INCOMPLETE` para evitar crear otro pedido a ciegas. Las nuevas rutas nunca confirman una reserva sin resultado.

## Verificacion

Las pruebas locales cubren replay, cambio de cuerpo, aislamiento de claves, rollback, recuperacion de pasos, version obsoleta y atomicidad del flujo de checkout. SQLite valida la logica transaccional; la contencion real entre conexiones PostgreSQL debe verificarse en integracion.
