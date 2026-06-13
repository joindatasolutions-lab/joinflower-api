# Diccionario de Datos - Caja

Fecha de levantamiento: 2026-06-12
Base de datos: `joinflower-dev`
Esquema: `petalops`

## Resumen

| Objeto | Tipo | Descripcion |
| --- | --- | --- |
| `caja` | Tabla | Registro diario unificado de caja por empresa, sucursal y fecha. |

## Reglas Principales

- Una caja diaria se identifica por `empresa_id`, `sucursal_id` y `fecha`.
- `base` es el efectivo inicial del dia. Debe corresponder a la `nueva_base` del dia anterior.
- `efectivo` es el efectivo que ingresa por pedidos del dia.
- `gasto` es el efectivo que sale de caja por compras u otros gastos operativos del dia.
- `guardado` es el dinero entregado o retirado al cierre.
- `total_efectivo = base + efectivo - gasto`.
- `nueva_base = base + efectivo - gasto - guardado`.

## Tabla `caja`

| Columna | Tipo | Nulo | Default | Descripcion |
| --- | --- | --- | --- | --- |
| `id_caja` | `bigint` | No | Secuencia | Identificador tecnico del registro. |
| `empresa_id` | `bigint` | No |  | Empresa propietaria de la caja. |
| `sucursal_id` | `bigint` | No |  | Sucursal donde opera la caja. |
| `fecha` | `date` | No |  | Fecha operativa de caja. |
| `base` | `numeric` | No | `0` | Efectivo inicial del dia. |
| `efectivo` | `numeric` | No | `0` | Efectivo ingresado por pedidos. |
| `gasto` | `numeric` | No | `0` | Salidas de efectivo del dia. |
| `total_efectivo` | `numeric` | No | `0` | `base + efectivo - gasto`. |
| `guardado` | `numeric` | No | `0` | Dinero entregado/retirado al cierre. |
| `nueva_base` | `numeric` | No | `0` | `total_efectivo - guardado`. |
| `observacion` | `text` | Si |  | Comentarios del cierre. |
| `usuario_id` | `bigint` | Si |  | Usuario que guarda el cierre. |
| `created_at` | `timestamp without time zone` | No | `CURRENT_TIMESTAMP` | Fecha/hora de creacion. |
| `updated_at` | `timestamp without time zone` | Si |  | Fecha/hora de ultima actualizacion. |

## Llaves y Relaciones

| Tipo | Columnas | Referencia / Regla |
| --- | --- | --- |
| Primary key | `id_caja` | Identificador unico del registro. |
| Unique | `empresa_id`, `sucursal_id`, `fecha` | Una caja diaria por empresa/sucursal/fecha. |
| Foreign key | `empresa_id` | `empresa.id_empresa` |
| Foreign key | `sucursal_id` | `sucursal.id_sucursal` |
| Foreign key | `usuario_id` | `usuario.id_usuario` |

## Migracion

La estructura se crea con:

```text
sql/alter_contabilidad_caja_unificada.sql
```

El script crea `petalops.caja` y migra datos desde las tablas anteriores si existen. La eliminacion de `caja_gasto` y `caja_apertura_cierre` queda comentada para ejecutarse manualmente despues de validar backups y datos.
