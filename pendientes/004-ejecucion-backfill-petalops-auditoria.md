# Pendiente 004 - Ejecucion backfill Petalops auditoria historica

## Fecha
2026-08-01

## Alcance ejecutado
Se ejecuto backfill solo para Petalops (`empresa_id = 2`) sobre `pedido_auditoria`.

## Script usado
`scripts/backfill_pedido_auditoria_historica.py --empresa-id 2 --apply`

## Resultado
- Pedidos Petalops sin auditoria antes: 21
- Auditorias insertadas: 21
- Pedidos Petalops sin auditoria despues: 0
- Accion insertada: `CREAR_PEDIDO_HISTORICO`
- Actor insertado: `system.backfill`

## Seguridad
Este backfill no cambia estados de pedido, no crea produccion, no modifica entrega, no toca pagos y no modifica detalle de pedido.

## Produccion faltante
No se ejecuto backfill de produccion para Petalops porque el diagnostico dio 0 pedidos aprobados sin produccion.

Los 212 aprobados sin produccion detectados pertenecen a Flora y tienen entrega pasada con estado entregado. No se debe crear produccion para esos pedidos sin validacion de negocio, porque podria reabrir trabajo historico en el modulo de Produccion.