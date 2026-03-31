# Instrucciones para el agente de código — Petalops

## Contexto del proyecto

Petalops es una plataforma SaaS multitenant para gestión de floristerías.
Cada floristería es una `empresa` con una o más `sucursal`.
El backend usa PostgreSQL con schema `petalops`.

Antes de escribir o modificar cualquier código que toque la base de datos,
lee el archivo `SCHEMA.md` en la raíz del repositorio. Ese archivo es la
fuente de verdad del modelo de datos.

---

## Reglas absolutas — nunca violarlas

### 1. Aislamiento multitenant
Toda query a cualquier tabla DEBE incluir filtro por `empresa_id`.
Sin excepción. Si una función recibe datos de un endpoint autenticado,
el `empresa_id` siempre viene del token JWT, nunca del body del request.

```sql
-- ✅ Correcto
SELECT * FROM petalops.pedido WHERE empresa_id = $1 AND id_pedido = $2;

-- ❌ Nunca hacer esto
SELECT * FROM petalops.pedido WHERE id_pedido = $2;
```

### 2. Transiciones de estado
Antes de cambiar el estado de un pedido, producción o entrega,
SIEMPRE validar que la transición sea válida consultando la tabla correspondiente.

```sql
-- Validar transición de pedido
SELECT 1 FROM petalops.transicion_estado_pedido
WHERE empresa_id = $1
  AND estado_origen_id = $2
  AND estado_destino_id = $3;
-- Si no retorna fila → rechazar el cambio con error de negocio
```

Las tres tablas de transición son:
- `transicion_estado_pedido` — para cambios en `pedido.estado_pedido_id`
- `transicion_estado_produccion` — para cambios en `produccion.estado_produccion_id`
- `transicion_estado_entrega` — para cambios en `entrega.estadoentregaid`

### 3. Numeración de pedidos
El número de pedido se obtiene con `SELECT FOR UPDATE` sobre `sucursal_contador_pedido`.
Nunca usar MAX(numero_pedido) + 1. Nunca usar una secuencia global.

```sql
-- Dentro de una transacción
UPDATE petalops.sucursal_contador_pedido
SET ultimo_pedido = ultimo_pedido + 1,
    updated_at = NOW()
WHERE empresa_id = $1 AND sucursal_id = $2
RETURNING ultimo_pedido;
```

### 4. Floristas
Un empleado es florista si y solo si existe en `perfil_florista`.
Para obtener floristas disponibles:

```sql
SELECT e.id_empleado, e.nombre_empleado, pf.capacidad_diaria, pf.trab_simul_permi
FROM petalops.empleado e
JOIN petalops.perfil_florista pf ON pf.empleado_id = e.id_empleado
WHERE e.empresa_id = $1
  AND e.activo = 1
  AND (pf.fecha_ini_incap IS NULL OR pf.fecha_fin_incap < NOW()
       OR pf.fecha_ini_incap > NOW());
```

### 5. Inventario — stock reservado vs stock real
- Al asignar insumos a una producción: incrementar `stock_reservado`, NO tocar `stock_actual`.
- Al confirmar consumo real: decrementar `stock_actual` y `stock_reservado`.
- Al cancelar producción: decrementar solo `stock_reservado`.
- Stock disponible real = `stock_actual - stock_reservado`.
- Todo movimiento debe insertarse en `movimiento_inventario`. Ese log es inmutable.

### 6. Intentos de entrega
Cada intento de entrega es una fila nueva en `entrega`.
Para obtener el estado actual de entrega de un pedido:

```sql
SELECT * FROM petalops.entrega
WHERE pedido_id = $1
ORDER BY intentonumero DESC
LIMIT 1;
```

### 7. Snapshots históricos — no modificar
Los siguientes campos son snapshots del momento de la transacción:
- `pedido_detalle.precio_unitario` — precio real cobrado
- `pedido_detalle.iva_unitario` — IVA real cobrado
- `entrega.barrionombre` — nombre del barrio al momento de la entrega

No actualizar estos campos bajo ninguna circunstancia después de la inserción.

### 8. Auditoría
- Reasignaciones de florista → insertar en `produccion_historial`
- Acciones administrativas sobre usuarios → insertar en `usuario_auditoria`
- Movimientos de inventario → insertar en `movimiento_inventario`

---

## Estructura de autenticación

- La autenticación vive en `usuario` (no en `empleado`).
- El `empresa_id` y `sucursal_id` del usuario autenticado se extraen del JWT.
- El rol del usuario está en `usuario.rolid` → FK a `rol`.
- Los permisos por módulo están en `permiso_modulo` (por rol) y `usuario_modulo` (override por usuario).
- Jerarquía de autorización de módulos (de mayor a menor precedencia):
  `plan_modulo` → `empresa_modulo` → `permiso_modulo` → `usuario_modulo`
  Un módulo debe estar activo en todos los niveles para que el usuario tenga acceso.

---

## Catálogo web

Para mostrar el catálogo de una sucursal:

```sql
SELECT
  ps.id_producto_sucursal,
  p.nombre_producto,
  p.descripcion,
  ps.precio,
  ps.imagen_url,
  ps.es_destacado,
  ps.orden_catalogo,
  c.nombre AS categoria
FROM petalops.producto_sucursal ps
JOIN petalops.producto p ON p.id_producto = ps.producto_id
JOIN petalops.categoria c ON c.id_categoria = p.categoria_id
WHERE ps.sucursal_id = $1
  AND ps.activo = true
  AND p.activo = true
ORDER BY ps.es_destacado DESC, ps.orden_catalogo ASC NULLS LAST;
```

---

## Flujo completo de un pedido

```
1. Cliente selecciona productos en catálogo web (producto_sucursal)
2. Se crea pedido + pedido_detalle (estado: PENDIENTE)
   → Incrementar sucursal_contador_pedido con FOR UPDATE
   → Si hay pasarela: crear registro en pago con checkouturl
3. Empleado aprueba o rechaza
   → Validar transición en transicion_estado_pedido
   → Si rechaza: guardar motivo_rechazo
4. Al aprobar: crear un registro en produccion por cada pedido_detalle
   → Asignar empleado_id (debe existir en perfil_florista)
   → Reservar stock en inventario
5. Florista actualiza estado de produccion
   → Validar transición en transicion_estado_produccion
   → Si reasigna florista: insertar en produccion_historial
6. Al completar producción: crear registro en entrega
   → Asignar domiciliarioid (empleado con cargo Domiciliario)
7. Domiciliario actualiza estado de entrega
   → Validar transición en transicion_estado_entrega
   → Si no entregado: puede crear nuevo intento (fila nueva en entrega con intentonumero+1)
   → Al entregar: registrar firma, foto, GPS, fechaentrega
8. Crear factura asociada al pedido
```

---

## Convenciones de código

- Siempre usar parámetros preparados (`$1`, `$2`, etc.) — nunca interpolación de strings.
- Todas las operaciones que involucren múltiples tablas deben ir en una transacción.
- Los errores de validación de negocio (transición inválida, florista no disponible, etc.)
  deben lanzarse como errores tipados, no como errores genéricos 500.
- Nombres de funciones: usar el nombre de la tabla como contexto.
  Ej: `pedidoService.aprobar()`, `produccionService.asignarFlorista()`, `entregaService.registrarIntento()`.
- Para queries complejas, agregar comentario con el propósito de la query antes del SQL.

---

## Deudas técnicas conocidas (no romper, solo documentar)

| tabla | campo | situación |
|---|---|---|
| empleado | usuario, email, password_hash, last_login | Legacy — autenticación real en tabla usuario |
| proveedor | (sin empresa_id) | Tabla global, pendiente aislar por empresa |
| produccion | fecha_fin / fecha_finalizacion | Dos campos con el mismo propósito — usar fecha_finalizacion |
| entrega | firma | Campo legacy, usar firmaimagenurl |

No eliminar estos campos aún — pueden tener datos en producción.
Documentar su deprecación en el código con comentario `// @deprecated`.
