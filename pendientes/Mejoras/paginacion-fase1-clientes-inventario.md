# Paginacion — Fase 1 (clientes e inventario, sin romper datos reales)

Relacionado con el punto 9 de [mejoras-arquitectura.md](./mejoras-arquitectura.md) ("Sin paginación consistente en todos los endpoints").

## Contexto: por que no se caculo el super usuario (empresa_id=1) como factor de riesgo aqui

Se valido `assert_same_empresa` (`app/core/security.py:762`): el super admin (`is_super_admin_context`) puede consultar cualquier empresa, pero **una a la vez** — cada endpoint sigue exigiendo un `empresa_id` explicito, nunca "todas las empresas combinadas" en un solo request. El riesgo de este punto no se amplifica por el rol de super usuario; es el mismo riesgo para cualquier empresa con muchos registros, sin importar quien lo consulte.

## Datos reales verificados antes de tocar codigo (dev DB, solo lectura)

| Tabla | empresa_id=1 (Join) | empresa_id=2 (Petalops) | empresa_id=3 (Flora) |
|---|---|---|---|
| `cliente` | 1 | 18 | **2409** |
| `inventario` | 0 | 3 | 2 |
| `producto` (catalogo) | 2 | 19 | 128 |

Flora ya tiene 2409 clientes. Cualquier default de paginacion por debajo de ese numero hubiera truncado silenciosamente su lista de clientes real — una regresion, no una mejora. Esto determino los defaults elegidos abajo.

## Cambios aplicados

### `GET /clientes` (`app/routers/cliente.py`)
- Nuevos params `page` (default 1) y `pageSize` (default **3000**, max 5000).
- Paginacion aplicada a nivel SQL (`.offset().limit()`) despues de `query.count()` para el total real.
- Respuesta ahora incluye `page` y `pageSize` ademas de `items`/`total`.
- Con el default de 3000, Flora (2409) sigue recibiendo todos sus clientes en un solo request — cero cambio de comportamiento hoy. El limite maximo de 5000 acota el peor caso (antes: literalmente sin limite).

### `GET /inventario` (`app/routers/inventario.py` + `app/schemas/inventario.py`)
- Nuevos params `page` (default 1) y `pageSize` (default 500, max 1000).
- **Diferencia importante con clientes:** los filtros `soloCriticos` y `estado` se aplican sobre un campo calculado en Python (`estadoStock`), no en una columna de BD, asi que no se puede paginar a nivel SQL sin romper esos filtros (paginar antes de filtrar daria un `total` y un contenido de pagina incorrectos). La paginacion se aplica en Python, **despues** de todos los filtros existentes, sobre la lista ya calculada.
- Esto no reduce la carga a la base de datos (sigue trayendo todas las filas que matchean los filtros), pero si acota el tamano de la respuesta final — que es el riesgo concreto que describe el punto 9. Con solo 2-3 registros reales hoy, no hay impacto visible.
- `InventarioListResponse` ahora incluye `page` y `pageSize`.

## Que NO se toco en esta fase (a proposito)

- **`/catalogo/{empresa_id}`**: mencionado en el documento original, pero se dejo fuera por dos motivos: (1) los conteos reales son chicos (max 128 productos, empresa Flora), sin riesgo actual; (2) el endpoint ya esta cacheado (ver [cache-fase1-memoria-segura.md](./cache-fase1-memoria-segura.md)) y la clave de cache actual no distingue por pagina — agregarle paginacion ahi requeriria tambien cambiar el esquema de cache key, lo cual se prefirio no mezclar en esta fase para no ampliar el alcance. Se revisita cuando el catalogo de alguna empresa crezca de verdad.
- **`barrios.py`**: ya tenia un `.limit(500 o 25)` hardcodeado (no es paginacion real, pero ya esta acotado) — no se toco.
- **No se coordino con el frontend.** Los defaults elegidos (3000 para clientes, 500 para inventario) son deliberadamente altos para no truncar ningun dato real hoy sin que el frontend tenga que cambiar nada. Cuando el frontend adopte `page`/`pageSize` de verdad, se pueden bajar estos defaults a valores mas chicos (ej. 50-100) para que la paginacion cumpla tambien su proposito de reducir carga, no solo de acotar el peor caso.

## Validado

- Sintaxis OK en los 3 archivos.
- `app.main` importa sin errores.
- Prueba funcional real (solo lectura) contra dev DB: `list_clientes(empresa_id=3, page=1, page_size=3000)` devuelve los 2409 clientes reales de Flora sin truncar. `list_clientes(empresa_id=3, page=2, page_size=1000)` devuelve correctamente los siguientes 1000 (el offset funciona). `listar_inventario` devuelve `page`/`pageSize` correctamente con los 2 registros reales de Flora.
