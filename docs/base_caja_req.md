# Requisitos De Caja

## Objetivo

Controlar la apertura, los movimientos de efectivo, el arqueo fisico y el cierre
diario sin trasladar sobrantes o faltantes como saldos negativos del dia siguiente.

## Datos Del Cierre

| Dato | Regla |
| --- | --- |
| Base inicial | Efectivo disponible al abrir la caja. |
| Ingresos en efectivo | Se calculan desde los pagos en efectivo de pedidos validos. |
| Gastos | Suma de movimientos registrados en `caja_gasto` para la empresa, sucursal y fecha. |
| Efectivo esperado | `base inicial + ingresos en efectivo - gastos`. |
| Total contado | Dinero fisico contado durante el arqueo. |
| Sobrante | `max(total contado - efectivo esperado, 0)`. |
| Faltante | `max(efectivo esperado - total contado, 0)`. |
| Caja menor | Dinero que permanece disponible como fondo operativo; se conserva en `caja.guardado` por compatibilidad. |
| Nueva base | `total contado - guardado`. |

## Validaciones

1. Base inicial, ingresos, gastos, total contado y guardado no pueden ser negativos.
2. Los gastos no pueden superar la base inicial mas los ingresos en efectivo.
3. El guardado no puede superar el total fisico contado.
4. Un faltante se registra como diferencia de arqueo; no se convierte en una
   nueva base negativa.
5. La nueva base del ultimo cierre anterior nunca se carga como un valor negativo.
6. Los valores calculados enviados por el frontend no son fuente de verdad; el
   backend recalcula efectivo esperado, sobrante, faltante y nueva base.
7. Cada gasto debe guardar fecha, concepto, descripcion, valor, tenant,
   sucursal y usuario. El consolidado de caja se actualiza en la misma
   transaccion que crea el movimiento.

## Ejemplo

- Base inicial: `$200.000`.
- Ingresos en efectivo: `$500.000`.
- Gastos: `$100.000`.
- Efectivo esperado: `$600.000`.
- Total contado: `$590.000`.
- Faltante: `$10.000`.
- Caja menor: `$500.000`.
- Nueva base: `$90.000`.

El faltante queda auditado por separado y no se descuenta nuevamente de la nueva
base, porque ya esta reflejado en el total fisico contado.

## Historial

El historial debe mostrar base, ingresos, gastos, efectivo esperado, total
contado, sobrante, faltante, guardado, nueva base y observacion. Los registros
anteriores a la implementacion del arqueo conservan `total contado` nulo y se
identifican como cierres historicos sin arqueo fisico registrado.
