# Punto 16 — indices para queries frecuentes (SQL preparado, no ejecutado)

Relacionado con el punto 16 de [mejoras-arquitectura.md](./mejoras-arquitectura.md).

## Validado contra la BD real de dev (solo lectura) antes de proponer nada

Volumen real hoy (no es aun el escenario de "100 floristerias" del documento):

| Tabla | Filas hoy |
|---|---|
| `pedido` | 3175 |
| `entrega` | 3174 |
| `produccion` | 3085 |
| `movimiento_inventario` | 7 |

A este volumen Postgres no sufre por falta de indices en la practica — el riesgo del documento es a futuro, no un problema de rendimiento activo hoy.

## Que ya estaba bien (sin tocar)

- `entrega`: ya tiene `idx_entrega_empresa_fecha (empresa_id, fechaentrega)` y `idx_entrega_empresa_fecha_programada (empresa_id, fechaentregaprogramada)` — exactamente lo que pedia el documento.
- `pedido`: ya tiene `idx_pedido_empresa_estado (empresa_id, estado_pedido_id)`.

## Gaps reales encontrados

1. **`pedido`**: falta un compuesto con fecha. El filtro mas comun (`/pedidos?empresaID=X&fechaDesde=Y&fechaHasta=Z`, ver `listar_pedidos` en `pedido.py`) no tiene indice compuesto de soporte.
2. **`produccion`**: tiene la columna `empresa_id` pero **cero indices sobre ella**, ni sola ni compuesta (solo hay indices sobre `sucursal_id`, `empleado_id`, `pedido_detalle_id`). Se confirmo en el codigo que `Produccion.empresaID` se filtra siempre (`_build_items` en `produccion.py`), casi siempre junto con `fecha_programada_produccion` (5+ lugares, incluido el job de autoasignacion).
3. **`movimiento_inventario`**: hallazgo que el documento original NO menciona — **dos indices identicos duplicados**: `idx_movimiento_empresa_fecha` e `idx_movinv_empresa_fecha`, ambos `btree (empresa_id, fecha)`, mismo tamaño (16 kB cada uno hoy). Cero beneficio de consulta adicional, solo overhead de escritura duplicado en cada INSERT/UPDATE para siempre.

## SQL preparado (NO ejecutado)

Archivo: `sql/alter_indices_empresa_fecha.sql` (repo `joinflower-api/sql`):

```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_pedido_empresa_fecha
    ON petalops.pedido (empresa_id, fecha_pedido);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_produccion_empresa_fecha
    ON petalops.produccion (empresa_id, fecha_programada_produccion);

DROP INDEX CONCURRENTLY IF EXISTS petalops.idx_movimiento_empresa_fecha;
```

Se eligio `CONCURRENTLY` en las 3 sentencias porque es el mecanismo estandar de Postgres para crear/borrar indices en una tabla viva sin bloquear lecturas ni escrituras — a diferencia de la rotacion del `JWT_SECRET` (que si desloguea a todos por diseño), esto se puede correr en cualquier momento, incluso con las floristerias trabajando, sin interrumpir a nadie.

**Nota tecnica:** `CREATE/DROP INDEX CONCURRENTLY` no puede correr dentro de una transaccion (`BEGIN/COMMIT`), por eso el archivo no la usa — cada sentencia se ejecuta y confirma por separado.

## Estado

**No ejecutado.** Queda pendiente de que el usuario confirme cuando quiera aplicarlo (puede ser en cualquier momento dado que `CONCURRENTLY` es seguro con trafico activo).
