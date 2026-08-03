# Caché en memoria — Fase 1 (memoria segura, Redis-ready)

Relacionado con el punto 2 de [mejoras-arquitectura.md](./mejoras-arquitectura.md) ("Caché en memoria — no funciona con múltiples instancias").

## Estado antes de esta fase

- `app/services/cache.py` tenía un diccionario en memoria por proceso (`_MEMORY_CACHE`), sin TTL configurable, sin manejo de error en la serialización y sin logs.
- TTLs hardcodeados en cada router:
  - `auth.py` (`empresa_config`): 300s
  - `catalogo.py`: 600s
  - `barrios.py`: 3600s (el más riesgoso — cambios de barrios/costos de domicilio podían tardar hasta 1h en propagarse entre instancias)

## Riesgo que motiva esta fase

Con Cloud Run corriendo varias instancias, cada una tiene su propio caché aislado. Un cambio de módulos/catálogo/barrios en una instancia no se refleja en las demás hasta que expira el TTL local. No es un problema de rendimiento, es de **consistencia temporal** entre instancias.

Se decidió NO meter Redis todavía (fase 2) porque implica infraestructura nueva (Memorystore, VPC connector), y hoy el volumen (10 floristerías) no lo justifica.

## Cambios aplicados en esta fase

### 1. `app/services/cache.py`
- Nuevas variables de entorno: `CACHE_BACKEND` (default `memory`), `CACHE_DEFAULT_TTL` (default `300`), `CACHE_DEBUG` (default `false`).
- Nueva función `cache_ttl(name, default)`: resuelve el TTL de un caché con nombre, permitiendo override puntual por env (`CACHE_TTL_<NAME>`) sin tocar código.
- `set_cache` ya no puede tumbar la request si el valor no es serializable: `json.dumps` ahora está en un `try/except`, y si falla se omite el cacheo (con warning en logs) en vez de propagar la excepción.
- Logs de hit/miss/expired/set/invalidate solo cuando `CACHE_DEBUG=true` (para no ensuciar logs en producción por defecto).
- Log de arranque que deja explícito `backend=memory` — visibilidad de que hoy el caché NO es compartido entre instancias.

### 2. TTLs bajados y hechos configurables
- `barrios.py`: `3600s` → `300s` (vía `cache_ttl("barrios", 300)`).
- `catalogo.py`: `600s` → `300s` (vía `cache_ttl("catalogo", 300)`; se puede subir a 600 con `CACHE_TTL_CATALOGO=600` si el catálogo resulta muy estable en la práctica, sin tocar código).
- `auth.py` (`empresa_config`): se mantiene en `300s`, ahora vía `cache_ttl("empresa_config", 300)`.

### 3. `.env.example`
- Documentadas las nuevas variables (`CACHE_BACKEND`, `CACHE_DEFAULT_TTL`, `CACHE_DEBUG`, `CACHE_TTL_*`).

### 4. Invalidación faltante al crear productos vía receta (`inventario.py`)

`catalogo.py` es de solo lectura — no crea productos. Se encontró que la creación de productos ocurre en `app/routers/inventario.py`, dentro de `_crear_producto_para_receta`, llamada desde dos endpoints:

- `POST /recetas` (`crear_receta`): crea un producto nuevo cuando se manda `precioVenta` sin `productoID`.
- `PUT /recetas/{receta_id}` (`actualizar_receta`): mismo caso.

Ninguno de los dos invalidaba el caché de `/catalogo/{empresa_id}`, así que el producto nuevo tardaba hasta el TTL (antes 600s, ahora 300s) en aparecer en el catálogo de esa sucursal.

**Fix aplicado:** nueva función `_invalidate_catalogo_cache(empresa_id, sucursal_id)` en `inventario.py`, que llama a `invalidate_cache_prefix(f"catalogo:{empresa_id}:sucursal:{sucursal_id}")`. Se invoca **después** del `db.commit()` exitoso en ambos endpoints (nunca antes, para no invalidar y que un request concurrente repueble el caché con datos aún no confirmados). Si `sucursal_id` es `None` (producto creado sin sucursal asociada), no hace nada — no hay nada que invalidar porque el producto no aparece en ningún catálogo por sucursal.

Probado de forma aislada (sin BD real): cachea una entrada `catalogo:5:sucursal:2`, se invoca la invalidación y se confirma que el caché queda vacío; y que con `sucursal_id=None` el caché existente no se toca.

**Nota (no bloqueante, no corregida en esta fase):** el prefijo `catalogo:{empresa_id}:sucursal:{sucursal_id}` podría, en teoría, sobre-invalidar si una sucursal es prefijo numérico de otra (ej. sucursal `1` vs `10`). El efecto sería invalidar de más (una sucursal vecina recalcula su catálogo antes de tiempo), nunca servir datos incorrectos. Igual que en `barrios.py`, se podría cerrar el prefijo con un separador final para eliminar la ambigüedad — queda anotado para una futura limpieza, no se tocó aquí para no ampliar el alcance de esta fase.

## Qué NO se hizo en esta fase (a propósito)

- No se instaló Redis ni se creó infraestructura nueva.
- No se tocó la firma de `get_cache` / `set_cache` / `invalidate_cache_prefix` que ya usan los routers — la migración a Redis en fase 2 debería limitar el cambio a `cache.py` + `requirements.txt` + env + infraestructura.

## Fase 2 (futuro, NO implementada aún)

Entra cuando: haya más de 2-3 instancias activas simultáneas, tráfico alto en catálogo/barrios, o se necesite invalidación inmediata entre instancias.

- Agregar backend Redis en `cache.py` seleccionable por `CACHE_BACKEND=redis` + `REDIS_URL=...`.
- Nueva dependencia en `requirements.txt` (cliente Redis).
- Infraestructura: Cloud Memorystore + VPC connector desde Cloud Run.
- Validar latencia y comportamiento de fallback si Redis no responde.
