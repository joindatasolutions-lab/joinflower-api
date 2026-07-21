# Deuda técnica: modelos ORM desincronizados de la base de datos real

**Estado:** dormida / sin impacto activo hoy — riesgo latente para desarrollo futuro.
**Detectada:** 2026-07-21, a raíz de un error 500 real en el módulo Contabilidad (`producto.image_url` no existía en la base). Ese caso puntual ya está corregido (ver [Caso ya resuelto](#caso-ya-resuelto-productoimage_url)). Al revisar por qué pasó, se comparó **todo** el catálogo de modelos SQLAlchemy contra el esquema real de PostgreSQL y aparecieron varios casos más del mismo patrón.

## Por qué importa esto para todas las empresas (no es un problema "por tenant")

Estos desajustes viven en la **definición del modelo en Python**, no en los datos de ninguna empresa puntual. Eso significa dos cosas:

1. **No es progresivo ni depende de cuántas empresas se vayan agregando.** No es que "la empresa 12 lo tenga y la 5 no" — es el mismo código para todas.
2. **Si algo lo dispara, se rompe para todas las empresas a la vez, de inmediato**, con un error 500 (`column does not exist` / `relation does not exist`), exactamente como pasó con `producto.image_url`.

El disparador típico: alguien (otro desarrollador, otra sesión de IA, o el mismo autor meses después) ve que ya existe un modelo con el nombre que necesita (`Categoria`, `Empleado`, etc.), asume que está al día, y lo usa directo con `db.query(...)` en vez de revisar primero el esquema real. En ese momento, la app se cae para toda la base de usuarios, no solo para quien lo escribió.

---

## Caso ya resuelto: `Producto.image_url`

- **Qué pasaba:** el modelo `Producto` (`app/models/producto.py`) declara `imageUrl = Column("image_url", Text)`. Esa columna existe en el código y en la migración `sql/alter_producto_image_url.sql` (parte de un merge de hace unos días), pero la migración nunca se ejecutó contra esta base de datos.
- **Por qué se disparó:** el módulo Contabilidad hace un `JOIN` real contra `producto` en `resumen_contabilidad` (`app/routers/pedido.py`), así que cualquier consulta a pedidos con detalle de producto lo tocaba.
- **Corrección aplicada:** se ejecutó la migración pendiente contra la base compartida. Cero cambios de código — el modelo y el uso ya eran correctos, solo faltaba aplicar el `ALTER TABLE`.
- **Lección:** este es el patrón exacto de riesgo que describe este documento. La diferencia es que este caso SÍ se usaba en producción, así que se notó rápido. Los de abajo no se usan todavía, así que están dormidos.

---

## Inventario de modelos desincronizados

| Modelo | Archivo | Tabla declarada | Tabla real | ¿Se usa hoy? | Severidad si se activa |
|---|---|---|---|---|---|
| `Categoria` | `app/models/categoria.py` | `categoria` (nombre OK) | `categoria` | Solo indirectamente vía `Producto.categoria` (relationship nunca recorrida) | Alta — columnas totalmente distintas |
| `TransicionEstadoPedido` | `app/models/transicionestadopedido.py` | `TransicionEstadoPedido` (PascalCase) | `transicion_estado_pedido` (snake_case) | Se importa en `pedido.py`, nunca se consulta | Alta — tabla no existe con ese nombre/case |
| `Empleado` | `app/models/empleado.py` | `Empleado` (PascalCase) | `empleado` (snake_case, ya cubierta por otros modelos) | Se importa en `pedido_service.py`, nunca se consulta | Media — redundante y roto, pero innecesario (ver abajo) |
| `SucursalContadorPedido` | `app/models/sucursal_contador_pedido.py` | `SucursalContadorPedido` | **No existe ninguna tabla así en la base** | No se usa en ningún router/service | Alta si se usa — no hay tabla que migrar, hay que decidir si se necesita |
| `Zona` | `app/models/zona.py` | `zona` (nombre OK) | **No existe la tabla** | Se pasa como parámetro (`zona: Zona \| None = None`) en `domicilios.py`, pero nunca se le hace `db.query()` | Baja — ya está evitado a propósito (commit `53dcf3c Avoid zona table dependency in domicilio lists`) |
| `PlanModulo` | `app/models/planmodulo.py` | `plan_modulo` (nombre OK) | `plan_modulo`, pero **sin la columna `empresa_id`** que el modelo declara | No se usa en ningún router/service | Baja — modelo completamente sin uso |

---

## Detalle por modelo

### 1. `Categoria`

**Modelo** (`app/models/categoria.py`):
```python
idCategoria   = Column("idcategoria", ...)
empresaID     = Column("empresaid", ...)
nombreCategoria = Column("nombrecategoria", ...)
descripcion   = Column("descripcion", ...)
orden         = Column("orden", ...)
activo        = Column("activo", ...)
createdAt     = Column("createdat", ...)
updatedAt     = Column("updatedat", ...)
```

**Tabla real `petalops.categoria`:**
```
id_categoria, empresa_id, nombre, created_at, activo
```

Ni los nombres coinciden (`idcategoria` vs `id_categoria`, `nombrecategoria` vs `nombre`) ni el número de columnas (`descripcion`, `orden`, `updated_at` no existen en la base). Además, `Producto.categoriaID` tiene su `ForeignKey("petalops.categoria.idcategoria")` apuntando a una columna que no existe (`idcategoria` en vez de `id_categoria`).

**Por qué no truena hoy:** nada navega la relación `Producto.categoria` ni hace `db.query(Categoria)`. Todo el código real (incluido el módulo de Arreglos hecho en esta sesión, en `app/routers/inventario.py`) usa SQL crudo con los nombres reales (`id_categoria`, `empresa_id`, `nombre`, `created_at`, `activo`).

**Cómo corregirlo:** reescribir `app/models/categoria.py` para que sus `Column(...)` mapeen los nombres reales, quitar `descripcion`/`orden`/`updatedAt` (no existen) o agregarlos a la base si de verdad se necesitan a futuro, y corregir el `ForeignKey` en `Producto.categoriaID`.

### 2. `TransicionEstadoPedido`

**Modelo:** tabla declarada `"TransicionEstadoPedido"` (con mayúsculas, lo que SQLAlchemy cita literalmente en el SQL generado). Columnas sin override de nombre (`idTransicionEstadoPedido`, `empresaID`, etc.) — SQLAlchemy buscaría columnas con esos nombres exactos, mayúsculas incluidas.

**Tabla real:** `petalops.transicion_estado_pedido` (snake_case), con columnas `id_trans_estado_ped, empresa_id, estado_origen_id, estado_destino_id, created_at`.

**Uso real:** el código que sí valida transiciones de estado de pedido (`_transicion_pedido_permitida` en `app/routers/pedido.py`) usa SQL crudo directo contra `petalops.transicion_estado_pedido` con los nombres reales — el import del modelo ORM en la línea 26 de ese archivo nunca se usa, es un import muerto.

**Cómo corregirlo:** o se borra el modelo (y su import) porque el flujo real ya está resuelto con SQL crudo, o se reescribe para que coincida con la tabla real si se planea migrar ese flujo a ORM más adelante.

### 3. `Empleado`

**Modelo:** tabla declarada `"Empleado"` (mayúsculas), con una sola columna (`idEmpleado`, sin override de nombre).

**Tabla real:** `petalops.empleado` (minúsculas) — que además **ya está correctamente mapeada** por otros dos modelos que sí funcionan: `Domiciliario` (`app/models/domiciliario.py`) y `Florista` (`app/models/florista.py`), ambos con `__tablename__ = "empleado"` y columnas bien mapeadas (`id_empleado`, `empresa_id`, `sucursal_id`, `nombre_empleado`, `cargo`, `activo`, etc.).

**Uso real:** se importa en `app/services/pedido_service.py` pero nunca se consulta.

**Cómo corregirlo:** este es el caso más simple — `Empleado` es completamente redundante, la tabla ya está bien cubierta por `Domiciliario`/`Florista`. Lo más limpio es **borrar `app/models/empleado.py` y su import**, no arreglarlo.

### 4. `SucursalContadorPedido`

**Modelo:** tabla declarada `"SucursalContadorPedido"`, con columnas `empresaID`, `sucursalID`, `ultimoPedido`, `updatedAt` (sin override de nombres).

**Tabla real:** no existe ninguna tabla con ese nombre en `petalops`, ni en mayúsculas ni en minúsculas ni con guiones bajos.

**Uso real:** no se importa ni se usa en ningún router o service actualmente.

**Cómo corregirlo:** antes de "arreglarlo" hay que decidir si este mecanismo (un contador de número de pedido por sucursal) todavía se necesita — el numerado de pedidos actual (`generar_numeracion_pedido` en `app/services/pedido_service.py`) puede que ya resuelva esto de otra forma. Si no se necesita, borrar el modelo. Si sí se necesita, crear la migración de la tabla y corregir el modelo.

### 5. `Zona`

**Modelo:** tabla declarada `"zona"` (nombre correcto), columnas `id_zona`, `nombre_zona` (bien mapeadas).

**Tabla real:** no existe la tabla en la base todavía.

**Uso real:** se usa como parámetro opcional (`zona: Zona | None = None`) en varias funciones de `app/routers/domicilios.py`, pero **nunca se le hace una consulta real** — siempre se le pasa `None`. Esto es intencional: hay un commit del propio merge de hace unos días llamado literalmente *"Avoid zona table dependency in domicilio lists"* (`53dcf3c`), es decir que el equipo que trajo esta funcionalidad ya sabía que la tabla no existe y lo evitó a propósito mientras tanto.

**Cómo corregirlo:** cuando se decida implementar zonas de verdad, crear la migración de la tabla `petalops.zona` y conectar los parámetros que hoy siempre reciben `None`. Mientras tanto no requiere acción — es el caso de menor riesgo de toda la lista porque ya está siendo evitado conscientemente.

### 6. `PlanModulo`

**Modelo:** declara `empresaID = Column("empresa_id", ...)`.

**Tabla real:** `petalops.plan_modulo` solo tiene `plan_id`, `modulo`, `activo` — no tiene `empresa_id`.

**Uso real:** no se usa en ningún router ni service.

**Cómo corregirlo:** modelo sin uso actualmente — quitar la columna `empresaID` del modelo, o agregarla a la tabla real si se planea usar el módulo con ese alcance (parece pensado para permitir módulos habilitados por empresa además de por plan).

---

## Cómo volver a chequear esto en el futuro

El script usado para detectar todos estos casos compara cada modelo SQLAlchemy registrado contra el esquema real de PostgreSQL. Es rápido (unos segundos) y no modifica nada — conviene correrlo después de cualquier merge grande que traiga modelos nuevos, antes de asumir que todo quedó aplicado correctamente:

```python
import app.main  # registra todos los modelos
from app.database import Base, engine
from sqlalchemy import inspect

insp = inspect(engine)
db_tables = {
    tname: {c["name"] for c in insp.get_columns(tname, schema="petalops")}
    for tname in insp.get_table_names(schema="petalops")
}

mismatches = []
for mapper in Base.registry.mappers:
    cls = mapper.class_
    table = cls.__table__
    tname = table.name
    if tname not in db_tables:
        mismatches.append(f"TABLE MISSING: {tname} (model {cls.__name__})")
        continue
    for col in table.columns:
        if col.name not in db_tables[tname]:
            mismatches.append(f"COLUMN MISSING: {tname}.{col.name} (model {cls.__name__}.{col.key})")

print("\n".join(mismatches) if mismatches else "NO MISMATCHES")
```

---

## Prioridad recomendada (si se decide atacar esta deuda)

1. **`Empleado`** — el más fácil y de menor riesgo: es puro borrado de un modelo redundante y su import.
2. **`Categoria`** — el de mayor riesgo real si alguien lo activa sin saber (la relación `Producto.categoria` está a un `joinedload()` de distancia de romper todo). Vale la pena corregirlo aunque hoy no truene.
3. **`TransicionEstadoPedido`** — bajo riesgo de uso (el flujo real ya está resuelto con SQL crudo), pero fácil de limpiar: borrar el import muerto o corregir el modelo si se planea usarlo.
4. **`PlanModulo`** — sin uso, bajo riesgo, corrección trivial cuando se retome.
5. **`SucursalContadorPedido`** y **`Zona`** — requieren primero una decisión de producto (¿se necesita esta funcionalidad?) antes de tocar código.

Ninguno de estos requiere acción inmediata. Este documento existe para que, cuando alguien vuelva a tocar categorías, transiciones de estado, empleados, zonas o límites de módulos por empresa, sepa de antemano dónde están las trampas en vez de descubrirlas con un 500 en producción.
