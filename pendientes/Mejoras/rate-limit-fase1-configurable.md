# Rate limiting — Fase 1 (limite de login bajado + configurable, Redis-ready)

Relacionado con el punto 3 de [mejoras-arquitectura.md](./mejoras-arquitectura.md) ("Rate limiting en memoria — no distribuido").

## Validacion real en Cloud Run (no era teorico)

Se conecto por gcloud CLI al proyecto `flora-471805` (joinflower-dev) y se inspecciono el servicio `join-flower` (region `us-central1`):

- `minScale`: 1
- `maxScale`: **10**
- `containerConcurrency`: 20 req/instancia

Esto confirma que el servicio SI escala a multiples instancias bajo carga, no esta fijado en 1. El rate limiting de SlowAPI usa storage en memoria por proceso (`get_remote_address` como key), asi que el limite efectivo por IP bajo carga alta podia llegar a `maxScale x limite_configurado`.

## Estado antes de esta fase

Solo 5 endpoints tenian rate limit (el resto de la API no tiene ninguno, eso no cambio en esta fase):

| Endpoint | Limite antes | Riesgo |
|---|---|---|
| `POST /login` | 30/minute | Bajo carga, hasta 10 x 30 = 300/min efectivos. Es el UNICO control anti fuerza-bruta (no hay bloqueo de cuenta por intentos fallidos en `app/core/security.py`). |
| `GET /pedidos` | 100/minute | Igual multiplicacion, pero es proteccion contra polling agresivo del front, no seguridad critica. |
| `POST /pedido/checkout` | 60/minute | Proteccion de abuso/doble-submit. |
| `POST /pedido/manual` | 60/minute | Igual. |
| `POST /pedido` | 60/minute | Igual. |

## Cambios aplicados en esta fase

### 1. `app/middlewares/rate_limit.py`
- Nueva variable de entorno `RATE_LIMIT_STORAGE_URI` (default `memory://`) pasada explicitamente a `Limiter(storage_uri=...)`. Se valido contra el codigo fuente instalado de `slowapi` que esto es identico al comportamiento por defecto actual (sin `storage_uri`, cae al mismo `"memory://"`) — cero cambio de comportamiento hoy.
- Nueva funcion `rate_limit(name, default)`: resuelve un limite (ej. `"10/minute"`) permitiendo override puntual por env `RATE_LIMIT_<NAME>` sin tocar codigo, mismo patron que `cache_ttl` en la fase 1 del cache.

### 2. Limite de login bajado: 30/minute -> 10/minute
- `app/routers/auth.py`: `@limiter.limit(rate_limit("login", "10/minute"))`.
- Es el unico cambio de comportamiento real de esta fase (los demas limites quedan en su valor original, solo se hicieron configurables).
- Con `maxScale=10`, el limite efectivo bajo carga alta baja de ~300/min a ~100/min. Sigue siendo por-instancia (no global), pero reduce la ventana de fuerza bruta sin esperar a Redis.
- Si algun local con varios empleados detras de la misma IP/NAT ve bloqueos legitimos en horas pico, subir con `RATE_LIMIT_LOGIN=20/minute` (o el valor que se necesite) sin tocar codigo ni redeploy de logica.

### 3. Resto de limites (pedidos) hechos configurables, sin cambiar su valor
- `pedidos_list`: 100/minute (sin cambio, ahora via `rate_limit("pedidos_list", "100/minute")`).
- `pedido_checkout`, `pedido_manual`, `pedido_crear`: 60/minute cada uno (sin cambio, ahora via `rate_limit(...)`).

### 4. `.env.example`
- Documentadas `RATE_LIMIT_STORAGE_URI`, `RATE_LIMIT_LOGIN` y los overrides opcionales de pedidos.

## Que NO se hizo en esta fase (a proposito)

- No se instalo Redis. `RATE_LIMIT_STORAGE_URI` sigue en `memory://` — el rate limit sigue siendo por-instancia, no global. Con `maxScale=10` esto sigue siendo una limitacion real, solo mitigada (limite mas bajo), no resuelta de raiz.
- No se agrego bloqueo de cuenta por intentos fallidos (no existia antes tampoco). El rate limit por IP es el unico control, y tiene un limite inherente: un atacante rotando IPs lo evade sin importar el backend (memoria o Redis). Eso no se resuelve en esta fase.
- No se le puso rate limit a los endpoints que hoy no lo tienen (catalogo, barrios, inventario, etc.) — fuera del alcance de este punto del documento.

## Fase 2 (futuro, NO implementada aun)

Cuando se implemente Redis para la fase 2 del cache ([cache-fase1-memoria-segura.md](./cache-fase1-memoria-segura.md)), activar rate limiting distribuido real es un cambio de una sola variable de entorno:

```
RATE_LIMIT_STORAGE_URI=redis://...
```

Sin tocar `auth.py`, `pedido.py` ni la logica de negocio. El mismo Redis (Memorystore + VPC connector) que se cree para el cache serviria para esto tambien — no es infraestructura adicional.
