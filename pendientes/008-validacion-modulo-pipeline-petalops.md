# Pendiente 008 - Validacion modulo pipeline Petalops

## Hallazgos

- Pipeline no tiene tablas propias; construye el tablero leyendo `pedido`, `estado_pedido`, `produccion`, `estado_produccion`, `entrega`, `estado_entrega`, `cliente`, `producto`, `empleado` y `sucursal`.
- `estado_pedido` contiene estados operativos antiguos/inactivos: `PENDIENTE_PRODUCCION`, `EN_PRODUCCION`, `LISTO`, `ENTREGADO` con `activo = 0`.
- La fuente correcta del pipeline debe ser:
  - Comercial: `pedido.estado_pedido_id` para `CREADO`, `APROBADO`, `CANCELADO`.
  - Produccion: `produccion.estado_produccion_id` para `pendiente_produccion`, `en_produccion`, `listo`.
  - Domicilios: `entrega.estadoentregaid` para `en_camino`, `entregado`, `cancelado`.
- El back tenia hardcodes de IDs para produccion y entrega en `_resolve_stage`; fue corregido para resolver por `codigo/nombre` del catalogo y dejar IDs solo como respaldo.
- El front tenia `STAGE_TO_ESTADO_ID` con IDs operativos inactivos (`3`, `4`, `5`, `20`). Eso podia cambiar solo el estado del pedido sin mover produccion/domicilios.

## Validacion Petalops

Conteo del endpoint `/pipeline/pedidos` para `empresa_id = 2`:

- `creado`: 20
- `aprobado`: 0
- `pendiente_produccion`: 10
- `en_produccion`: 1
- `listo`: 7
- `en_camino`: 2
- `entregado`: 10
- `cancelado`: 6
- Total: 56

La consulta no cambio datos: pedidos antes 56, despues 56.

## Inconsistencias historicas detectadas

- Pedidos cancelados con entrega pendiente:
  - `PTL-00007` / pedido `2787`
  - `PTL-00009` / pedido `2789`
- Pedido aprobado con entrega `entregado` pero produccion `pendiente`:
  - `PTL-00016` / pedido `2837`

No se corrigieron automaticamente porque cambiar esos estados puede afectar visibilidad en Produccion/Domicilios y debe revisarse caso por caso.

## Cambios realizados

- Back: `app/routers/pipeline.py` resuelve etapas por catalogo real (`codigo/nombre`) y no por IDs fijos.
- Back tests: se agregaron casos para `_resolve_stage`.
- Front: `STAGE_TO_ESTADO_ID` queda limitado a estados comerciales seguros: `creado`, `aprobado`, `cancelado`.
- Front: si se intenta arrastrar a una etapa operativa, se muestra aviso para usar Produccion o Domicilios.

## Recomendacion para produccion

- Mantener pipeline como tablero de lectura/orquestacion, no como motor de transiciones operativas.
- Para mover a produccion: usar endpoints de Produccion.
- Para mover a domicilio/en camino/entregado: usar endpoints de Domicilios.
- No reactivar estados operativos en `estado_pedido`; dejarlos como historicos/inactivos o eliminarlos del front.