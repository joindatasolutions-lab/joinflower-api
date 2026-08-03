# Deuda ORM desincronizada — Fase 1 (los 4 items sin decision de producto pendiente)

Relacionado con el punto 6 de [mejoras-arquitectura.md](./mejoras-arquitectura.md) y con el diagnostico ya existente en `docs/deuda_tecnica_modelos_orm_desincronizados.md` (2026-07-21).

## Re-validacion contra la BD real (dev) antes de tocar nada

Se corrio el script de deteccion que el propio doc de deuda tecnica provee (compara `Base.registry.mappers` contra `information_schema` real). Resultado antes de esta fase:

```
TABLE MISSING: zona (model Zona)
COLUMN MISSING: plan_modulo.empresa_id (model PlanModulo.empresa_id)
TABLE MISSING: Empleado (model Empleado)
COLUMN MISSING: categoria.idcategoria/empresaid/nombrecategoria/descripcion/orden/createdat/updatedat
TABLE MISSING: SucursalContadorPedido (model SucursalContadorPedido)
```

5 de los 6 casos del doc original seguian exactamente igual. El sexto (`TransicionEstadoPedido`) **ya estaba corregido** desde que se escribio el doc — el modelo mapea correctamente contra `transicion_estado_pedido`, solo quedaba un import muerto.

## Cambios aplicados (los 4 sin decision de producto pendiente)

### 1. `Empleado` — borrado completo
- Eliminado `app/models/empleado.py`.
- Eliminado el import en `app/services/pedido_service.py:12` (unica referencia en todo el repo).
- Confirmado que `Empleado` NO estaba en `app/models/__init__.py` (a diferencia de los otros 5 modelos de la lista, que si estan ahi y por eso siguen "registrados" en SQLAlchemy aunque nadie los use directo).
- La tabla real `empleado` sigue correctamente cubierta por `Domiciliario` y `Florista`.
- Validado: `from app.models.empleado import Empleado` ahora lanza `ModuleNotFoundError` (esperado), y `app.main` sigue importando sin errores.

### 2. `TransicionEstadoPedido` — solo se quito el import muerto
- Eliminada la linea `from app.models.transicionestadopedido import TransicionEstadoPedido` en `app/routers/pedido.py:26` (nunca se usaba; la validacion real de transiciones usa SQL crudo).
- El modelo NO se borro — sigue correctamente mapeado (via `app/models/__init__.py`) por si se quiere usar a futuro.

### 3. `Categoria` — columnas corregidas para matchear la BD real
- `app/models/categoria.py`: `idCategoria` -> `id_categoria`, `empresaID` -> `empresa_id` (con `ForeignKey` corregido a `petalops.empresa.id_empresa`), `nombreCategoria` -> `nombre`, `createdAt` -> `created_at`. Se eliminaron `descripcion`, `orden` y `updatedAt`: no existen en la tabla real.
- `app/models/producto.py`: el `ForeignKey` de `Producto.categoriaID` apuntaba a `petalops.categoria.idcategoria` (columna inexistente); corregido a `petalops.categoria.id_categoria`.
- **Validado con datos reales de dev** (solo lectura): `db.query(Categoria).limit(3).all()` funciona y trae datos reales (ej. "Flora Canastos", "Maderas"), y el join `Producto` -> `Categoria` (`db.query(Producto).join(Categoria, ...)`) tambien funciona — antes de este fix, cualquiera de las dos operaciones hubiera lanzado `column does not exist`.

### 4. `PlanModulo` — columna inexistente eliminada del modelo
- `app/models/planmodulo.py`: se quito `empresaID = Column("empresa_id", ...)` porque `plan_modulo` no tiene esa columna en la BD real.
- Se confirmo que `app/core/security.py` (la unica logica real que lee `plan_modulo`) usa SQL crudo dinamico con su propio resolver de columnas, sin depender del modelo ORM ni referenciar `empresa_id` — cero impacto.
- Validado con datos reales de dev: `db.query(PlanModulo).limit(3).all()` funciona (ej. "pedidos", "produccion", "domicilios").

## Que NO se toco en esta fase

`SucursalContadorPedido` (tabla no existe) y `Zona` (tabla no existe) — ambos requieren primero decidir si esas funcionalidades se van a implementar antes de escribir cualquier migracion o cambio de modelo. Ver seccion siguiente.

## Validacion final

- Sintaxis OK en los 5 archivos tocados.
- `app.main` importa sin errores.
- Re-corrido el detector de mismatches: `Empleado`, `Categoria` y `PlanModulo` ya NO aparecen. Solo quedan `zona` y `SucursalContadorPedido`, exactamente los 2 pendientes de decision de producto.
- Pruebas ORM reales contra BD de dev (solo lectura) para `Categoria` y `PlanModulo`.
