# Puntos 14 y 15 — observabilidad por tenant y job de autoasignacion

Relacionado con los puntos 14 y 15 de [mejoras-arquitectura.md](./mejoras-arquitectura.md).

## Punto 14 — empresa_id agregado al contexto de logs (implementado)

### Antes
`app/core/middleware.py` (`RequestContextMiddleware`) ya inyectaba `request_id` en cada log via un `contextvars.ContextVar`, pero no habia forma de saber que empresa disparo un error sin revisar el payload del JWT o los parametros de cada request.

### Por que no se toco `get_current_auth_context` directamente
Se evaluo agregar el `empresaID` al contexto de logs adentro de `get_current_auth_context` (`app/core/security.py`), convirtiendola en una dependencia `yield` (mismo patron que usa FastAPI para cleanup). Se descarto: **hay 3 llamadas directas** a esa funcion (no via `Depends`) en `app/routers/auth.py` (lineas 740, 786, 810). Convertirla en generador hubiera roto esas 3 llamadas (recibirian un objeto generador en vez de un `AuthContext`).

### Cambio aplicado (mas seguro, sin tocar la autenticacion real)
- `app/core/logger.py`: nuevo `contextvars.ContextVar` `_empresa_id_ctx` + `set_empresa_id`/`reset_empresa_id`/`get_empresa_id`, mismo patron que ya existia para `request_id`. El formato de log ahora incluye `empresa=%(empresa_id)s`.
- `app/core/middleware.py`: nueva funcion `_extract_empresa_id_for_logs(request)` que lee el header `Authorization: Bearer <token>`, decodifica el JWT (mismo `JWT_SECRET`/`JWT_ALGORITHM` que la autenticacion real) **solo para taggear logs**. Si el token falta, es invalido o expiro, devuelve `"-"` sin lanzar ningun error — nunca bloquea la request. La autorizacion real sigue siendo responsabilidad exclusiva de `get_current_auth_context`, sin cambios.

### Validado
- Sintaxis OK, `app.main` importa sin errores.
- Prueba funcional con `TestClient`: request sin token loguea `empresa=-`; request con JWT valido (`empresaID=3`) loguea `empresa=3`. Confirmado en la salida real del logger configurado (`configure_logging()`), no simulado.

## Punto 15 — job de autoasignacion: ya resuelto, no requiere cambios

El documento describe el riesgo de que el job de autoasignacion (`app/jobs/produccion_autoassign_job.py`) corra en paralelo en cada instancia de Cloud Run y genere asignaciones duplicadas.

**Al revisar el codigo actual, el riesgo ya esta mitigado:** `run_autoassign_today_once()` usa `pg_try_advisory_lock` de PostgreSQL (`_acquire_advisory_lock`/`_release_advisory_lock`, clave fija `AUTOASSIGN_LOCK_KEY`) antes de hacer cualquier asignacion. Si varias instancias despiertan al mismo tiempo (las 10 instancias de `join-flower` calculan el mismo horario porque leen el mismo `PRODUCCION_AUTOASSIGN_SCHEDULE`), **solo una consigue el lock** y ejecuta; las demas ven `pg_try_advisory_lock` devolver `false`, retornan de inmediato (`locked: 1` en el resumen) sin tocar ninguna produccion.

Esto es exactamente el mecanismo de "lock distribuido" que sugeria el documento original (la alternativa a Redis), implementado con Postgres — sin agregar infraestructura nueva. El lock se libera explicitamente en el `finally` (`_release_advisory_lock` + `db.commit()`) antes de cerrar la sesion, asi que no queda colgado si el job falla a la mitad.

Se confirmo via `git log` que esto se agrego en el commit "Improve production search and scheduled auto-assignment" — posterior a cuando se redacto el documento original, por eso ese punto ya no aplica tal como esta descrito.

**No se aplico ningun cambio de codigo para este punto.**
