# RESUELTO (parcial) — agotamiento del pool de conexiones a la BD

**Estado: mitigado (2026-08-05), no resuelto de raiz.** Se bajo el pool por instancia para dejar de chocar contra el limite real de Postgres. El problema de fondo (tier de Cloud SQL demasiado chico) sigue sin resolverse.

Encontrado al validar errores de produccion de los ultimos 2 dias (pedido del usuario), no relacionado con ningun cambio de esta sesion — confirmado con logs que el error ya ocurria desde el 2026-07-09, casi un mes antes.

## El problema

Logs reales de Cloud Run mostraban, repetido 114 veces en 30 dias (48 solo en las ultimas 48h, concentrado en rafagas de trafico):

```
QueuePool limit of size 8 overflow 4 reached, connection timed out, timeout 30.00
```

Afectaba multiples modulos al mismo tiempo (`/auth/me`, `/pedidos`, `/catalogo`, `/produccion`, `/domicilios`, `/pedido/detalle`) porque no es un bug de un endpoint puntual — es que se agotan las conexiones disponibles a Postgres.

## Causa raiz real (validada, no supuesta)

- Cloud SQL (`joindata`, proyecto `flora-471805`) corre en tier **`db-f1-micro`** — el mas chico de GCP (shared-core, ~0.6 GB RAM).
- `SHOW max_connections` en Postgres real: **25**. Confirmado con `pg_stat_activity` que ya habia 26 conexiones activas al momento de revisar (3 reservadas para `cloudsqladmin`).
- Cloud Run tenia `DB_POOL_SIZE=8` + `DB_MAX_OVERFLOW=4` = **12 conexiones por instancia**. Con `maxScale=10`, el peor caso teorico eran **120 conexiones** posibles — muy por encima de las 25 reales. Con solo 2 instancias activas simultaneas (algo normal en una rafaga), ya se llegaba a 24, dejando casi nada de margen.
- Se confirmo que estos valores (8/4) ya estaban configurados en Cloud Run **antes** de esta sesion (el default en `app/database.py` es 3/2; alguien los habia subido manualmente en el pasado, probablemente como intento previo de mitigar este mismo problema, pero de forma insuficiente dado el tier de BD tan chico).

## Cambio aplicado

Se bajo el pool por instancia para que, incluso en el peor caso de 10 instancias simultaneas, el total nunca supere 20 conexiones (dejando 5 de margen sobre el limite real de 25):

```bash
gcloud run services update join-flower \
  --project=flora-471805 --region=us-central1 \
  --update-env-vars="DB_POOL_SIZE=2,DB_MAX_OVERFLOW=0"
```

Revision desplegada: `join-flower-00210-9mk`, 100% del trafico. `.env.example` actualizado con los mismos valores y una nota explicando el porque (para que nadie vuelva a subirlos sin saber del limite de 25).

## Por que esto es un parche, no la solucion de fondo

Bajar el pool evita que la suma de conexiones de todas las instancias choque contra el techo de Postgres, pero **no aumenta la capacidad real de la BD** — solo reparte mejor un recurso que sigue siendo muy chico. Con mas trafico (mas floristerias, mas pedidos simultaneos), esto puede volver a manifestarse como latencia/timeouts dentro de una misma instancia (esperando que se libere una de sus 2 conexiones), aunque ya no deberia tumbar toda la BD por exceder el limite duro.

## Opciones de fondo, no aplicadas todavia (requieren decision del usuario)

1. **Subir el tier de Cloud SQL** (`db-f1-micro` -> algo con mas RAM, ej. `db-g1-small` o un `db-custom`). Sube el `max_connections` real de forma proporcional. Tiene costo mensual adicional, no cuantificado aqui — revisar en la consola de GCP antes de decidir.
2. **PgBouncer** (connection pooling real) entre la app y Postgres — multiplexa muchas conexiones de la app en pocas conexiones reales, desacopla el escalado de Cloud Run del limite fijo de la BD. Es la solucion que ya sugeria el documento original de arquitectura (punto 1). Requiere agregar infraestructura nueva.
3. Revisar si `maxScale=10` en Cloud Run es realmente necesario para el trafico actual, o si limitarlo (ej. a 4-5) reduce el riesgo sin agregar infraestructura.

## Validado

- `GET /health` -> `200`, `GET /` -> `200` despues del cambio.
- Revision `join-flower-00210-9mk` activa con 100% del trafico.
- No se volvio a probar bajo una rafaga real de trafico (no se puede simular sin afectar produccion) — el efecto real se vera en la proxima hora pico.
