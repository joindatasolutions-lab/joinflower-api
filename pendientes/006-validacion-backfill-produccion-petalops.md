# Pendiente 006 - Validacion y backfill Produccion Petalops

## Fecha
2026-08-01

## Alcance ejecutado
Se valido Produccion para Petalops (`empresa_id = 2`) y se aplicaron cambios equivalentes a Pedidos:

- Poblar `transicion_estado_produccion` con reglas base.
- Validar transiciones desde tabla en backend.
- Registrar historial de cambios normales de estado en `produccion_historial`.
- Backfill seguro de historial de estado para producciones historicas Petalops.

## Tablas revisadas
- `estado_produccion`
- `transicion_estado_produccion`
- `produccion`
- `produccion_historial`
- `pedido`
- `pedido_detalle`
- `entrega`
- `estado_pedido`
- `estado_entrega`
- `empleado`
- `perfil_florista`
- `usuario`

## Reglas de transicion Petalops
- `pendiente -> en_proceso`
- `pendiente -> cancelado`
- `en_proceso -> terminado`
- `en_proceso -> cancelado`

## Backfill aplicado
Script usado:

```bash
python scripts/backfill_produccion_historial_estados.py --empresa-id 2 --apply
```

Resultado:
- Producciones Petalops sin historial explicito de estado antes: 16
- Historiales insertados: 16
- Faltantes despues: 0
- Actor: `system.backfill`

## Seguridad
No se cambiaron estados de produccion, no se crearon producciones, no se tocaron pedidos, entregas, pagos ni detalles. Solo se insertaron registros de historial.

## Laboratorio rollback
Se ejecuto laboratorio completo con Petalops:

1. `POST /pedido/checkout`
2. `PUT /pedido/{id}/aprobar`
3. `PUT /produccion/{id}/asignar`
4. `PUT /produccion/{id}/estado` a `EnProduccion`
5. `PUT /produccion/{id}/estado` a `ParaEntrega`

Usuarios:
- Admin: `admin_petalops`
- Florista: `florista_prueba`

El laboratorio corrio dentro de transaccion con rollback. Los conteos finales quedaron iguales a los iniciales.