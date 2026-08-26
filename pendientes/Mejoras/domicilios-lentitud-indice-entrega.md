# RESUELTO — lentitud al asignar domiciliario y al listar Domicilios

**Estado: resuelto (2026-08-23).** Reportado como "asignar un domiciliario a una entrega Lista para entrega se demora 5-10 segundos, guardando... el resto de la app no se demora nada".

## Diagnostico

Confirmado con logs reales de Cloud Run (2026-08-23, ventana de segundos): el propio `PUT /domicilios/{id}/asignar` (6.7s) no era el mas lento — al mismo tiempo, las 5 pestanas del modulo Domicilios (`filtro=hoy/pendientes/enruta/manana/entregado`) tardaban entre 12 y 24 segundos cada una. Dos causas combinadas:

1. **Consulta cara en cada peticion a `GET /domicilios`**: `_latest_entrega_id_subquery` (`app/routers/domicilios.py`) calcula "cual es el ultimo intento de entrega de cada pedido" con dos `GROUP BY` seguidos sobre TODA la tabla `petalops.entrega` de la empresa, sin limite de fecha, en cada llamada. La tabla no tenia ningun indice sobre `empresa_id`/`pedido_id`, forzando un `Seq Scan` completo cada vez.
2. **Pool de conexiones insuficiente para la capacidad real de la BD** (ver `pool-conexiones-agotado.md`): al cambiar rapido entre las 5 pestanas, el navegador dispara 5 peticiones casi simultaneas que agotaban las 5 conexiones disponibles por instancia de Cloud Run (`DB_POOL_SIZE=4`+`DB_MAX_OVERFLOW=1`), dejando al resto de peticiones (incluyendo el boton "Asignar") esperando en cola hasta 30s por una conexion libre. Esta es la causa dominante de los 12-24s observados — con solo 3,694 filas en `entrega` para la empresa, un `Seq Scan` sin indice no deberia tardar mas de unos pocos milisegundos por si solo.

## Cambios aplicados

1. **Indice nuevo** en `petalops.entrega`, cubre exactamente el patron de `_latest_entrega_id_subquery`:
   ```sql
   CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_entrega_empresa_pedido_intento
       ON petalops.entrega (empresa_id, pedido_id, intentonumero);
   ```
   Archivo: `sql/alter_indice_entrega_pedido_intento.sql`. Ejecutado manualmente por el usuario via DBeaver (la escritura automatica a la BD de produccion fue bloqueada por el clasificador de seguridad de Claude Code, que impide que el agente ejecute DDL directo contra produccion incluso con confirmacion en el chat).

2. **Pool de conexiones subido** de 4+1 a 10+5 en `join-flower` — ver detalle en `pool-conexiones-agotado.md`.

## Validado

- `EXPLAIN (ANALYZE, BUFFERS)` sobre la consulta real, ANTES vs DESPUES del indice: paso de `Seq Scan` a `Index Only Scan using idx_entrega_empresa_pedido_intento`. Tiempo de ejecucion medido por Postgres: **11.8 ms** (antes: consistente con los 12-24s observados en produccion via logs, aunque ese numero mezclaba tiempo de espera de conexion + ejecucion, no solo ejecucion).
- Indice confirmado valido (`indisvalid=true`, `indisready=true` en `pg_index` — no quedo `INVALID` por algun fallo silencioso de `CONCURRENTLY`).
- `gcloud sql instances describe`: tier `db-custom-2-8192`, `max_connections=400`, solo 24 conexiones activas en el momento de revisar — confirma que subir el pool era seguro.
- Deploy de `join-flower` con el pool nuevo: revision `join-flower-00236-dtz`, 100% trafico, `GET /health` -> 200, `GET /` -> 200.
- No se pudo medir un "antes/despues" end-to-end real de `PUT /domicilios/{id}/asignar` bajo una rafaga identica de trafico (no se puede simular sin afectar produccion) — el efecto real se debe confirmar con el usuario probando el modulo en un momento de uso normal con varios usuarios.

## Nota para el futuro

Si esta misma sensacion de lentitud vuelve a aparecer en Domicilios a pesar de este fix, lo mas probable es que ya no sea por falta de indice (esto quedo resuelto) sino por el pool de conexiones otra vez quedandose corto segun crezca el trafico real — revisar `DB_POOL_SIZE`/`DB_MAX_OVERFLOW` de `join-flower` y `pg_stat_activity` antes de asumir que es un problema de query.
