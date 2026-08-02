# Pendiente 005 - Front pedidos y pipeline IDs de estado

## Validacion realizada
Se reviso el front en `src` sin modificar archivos.

## Resultado
- La pantalla de Pedidos crea pedidos con `POST /pedido/checkout`.
- La aprobacion usa `PUT /pedido/{pedido_id}/aprobar`.
- El rechazo usa `PUT /pedido/{pedido_id}/rechazar`.
- La cancelacion de pedidos aprobados usa `PUT /pedido/{pedido_id}/estado/{nuevo_estado_id}` con `CANCELADO_PEDIDO_ESTADO_ID = 6`.
- Pipeline usa `STAGE_TO_ESTADO_ID` con IDs fijos: creado 1, aprobado 2, pendiente_produccion 3, en_produccion 4, listo/en_camino 5, entregado 20, cancelado 6.

## Riesgo
Aunque el backend ya dejo de depender del ID fijo `6` para detectar pedidos cancelados, el front todavia envia IDs fijos. Si los IDs de `estado_pedido` cambian en otra BD o entorno, el front podria enviar un destino incorrecto.

## Recomendacion
Exponer o consumir un endpoint/catalogo de estados de pedido y mapear por nombre/codigo, no por IDs quemados en el front. Alternativa minima: centralizar los IDs en una configuracion por entorno mientras se implementa el catalogo real.