# Resolver novedades de Domicilios

## Resolver

`PUT /domicilios/{entrega_id}/resolver-novedad`

Enviar `multipart/form-data`. No enviar JSON. Requiere autenticación y permisos
`domicilios.puedeVer` y `domicilios.puedeEditar`.

| Campo | Requerido | Descripción |
|---|---|---|
| `usuarioCambio` | Sí | Campo conservado por compatibilidad. El usuario responsable real se obtiene del token. |
| `observaciones` | Sí | Texto no vacío que explica la resolución. |
| `accion` | No | `entregar` (predeterminado), `nuevo_intento` o `devolver_disponibles`. |
| `reprogramarPara` | No | Fecha ISO 8601 para reintentar o devolver. Usar hora de Colombia; por ejemplo `2026-11-11T09:00:00-05:00`. |

Para `entregar` también están disponibles los campos opcionales existentes:
`firmaNombre`, `firmaDocumento`, `firmaImagenUrl`, archivo `firmaImagen`,
`evidenciaFotoUrl`, archivo `evidenciaFoto`, `latitudEntrega` y `longitudEntrega`.
Estos campos de evidencia solo se procesan con `entregar`.

Ejemplos de campos de formulario:

```text
usuarioCambio=admin
accion=entregar
observaciones=Cliente recibió el pedido después de confirmar la dirección.
```

```text
usuarioCambio=admin
accion=nuevo_intento
observaciones=Cliente confirmó disponibilidad mañana.
reprogramarPara=2026-11-11T09:00:00-05:00
```

```text
usuarioCambio=admin
accion=devolver_disponibles
observaciones=Reasignar a otro domiciliario.
```

| Acción | Resultado |
|---|---|
| `entregar` | Cierra la novedad, marca `Entregado`, registra fecha de entrega y encola WhatsApp de entrega. |
| `nuevo_intento` | Conserva el intento fallido y crea otra fila con `intentoNumero + 1`. Mantiene al domiciliario y queda `Asignado`; si no había domiciliario, queda `Pendiente`. Valida capacidad. La respuesta contiene el ID nuevo. |
| `devolver_disponibles` | Conserva el mismo intento, lo deja `Pendiente`, elimina domiciliario, fecha de asignación y salida. Conserva el motivo histórico. Su aparición en disponibles sigue los filtros operativos de fecha y producción. |

Respuesta:

```json
{"status":"ok","idEntrega":123,"estado":"Asignado"}
```

La entrega debe pertenecer a la empresa del token, ser el intento vigente y estar
en `NoEntregado`. Se bloquea la fila durante la operación. Un domiciliario solo
puede resolver su entrega; los administradores conservan su alcance administrativo.
Los demás usuarios necesitan los permisos del módulo. No se permite un domiciliario
sin vínculo con empleado. El cliente no puede elegir la empresa ni el actor de auditoría.

Se consulta `transicion_estado_entrega` para la empresa sin insertar permisos de
transición desde esta operación. Las salidas son `NoEntregado → Entregado`,
`NoEntregado → Asignado` o `NoEntregado → Pendiente`.

Errores: `403` por permisos/alcance, `404` por entrega inexistente en la empresa,
`409 DOMICILIO_STALE_ATTEMPT` por intento antiguo, `400 DOMICILIO_NOVEDAD_REQUIRED`
si no está en `NoEntregado`, `400` por transición no configurada y `422` por acción
inválida u observación vacía. También aplican los errores existentes de capacidad.

La resolución y sus efectos se confirman en una misma transacción. Auditoría guarda
usuario autenticado, fecha de Colombia, observación, acción y, cuando corresponde,
ID del nuevo intento y domiciliario anterior.

## Historial y contadores

`GET /domicilios/novedades`

Requiere `domicilios.puedeVer`. La empresa proviene del token. Los domiciliarios ven
los reportes que les corresponden, incluso después de liberar la entrega.

Parámetros opcionales: `estado=abierta|resuelta`, `pedidoID`, `sucursalID`,
`limite` (1–200, predeterminado 50), `offset` (predeterminado 0).
Sin `estado`, devuelve ambas clases, ordenadas por ID de reporte descendente.

```json
{
  "items": [{
    "idNovedad": 71,
    "pedidoID": 20,
    "idEntrega": 10,
    "domiciliarioID": 48,
    "estado": "resuelta",
    "motivo": "Cliente ausente",
    "observaciones": "No contesta el teléfono",
    "reportadaPor": "domi",
    "reportadaEn": "2026-11-10T09:00:00",
    "accionResolucion": "nuevo_intento",
    "observacionResolucion": "Cliente confirmó disponibilidad mañana",
    "resueltaPor": "admin",
    "resueltaEn": "2026-11-10T10:00:00",
    "nuevaEntregaID": 123
  }],
  "abiertas": 2,
  "resueltas": 5,
  "total": 7
}
```

`abiertas` y `resueltas` cuentan todos los reportes dentro del alcance y los filtros
de pedido/sucursal, antes de paginar y sin aplicar `estado`. `total` sí aplica
`estado`. En una novedad abierta los campos de resolución son `null`.

El historial usa `domicilio_auditoria`; `idNovedad` es el ID del evento de reporte,
no una fila de `domicilio_novedad`. Reconoce reportes `NO_ENTREGADO` y
`MARCAR_NO_ENTREGADO`, y cierres explícitos `RESOLVER_NOVEDAD`, `ENTREGADO`,
`DEVOLUCION` y `REINTENTO_ASIGNADO`. Los cierres antiguos pueden devolver el nombre
del evento en `accionResolucion` y no tener observación. Un cambio de estado
arbitrario no se interpreta como cierre. Entregas antiguas sin evento de reporte
no se reconstruyen automáticamente como novedades.

Los contadores nuevos se consumen desde esta respuesta. `/domicilios/contadores`
mantiene sus contadores operativos existentes; las métricas históricas basadas
en `motivoNoEntregado` no deben utilizarse como contador de novedades abiertas.

## Otros endpoints existentes

- `PUT /domicilios/{id}/no-entregado`: JSON con `usuarioCambio`, `motivo` (mínimo
  4 caracteres), y opcionales `observaciones`, `reprogramarPara`.
- `PUT /domicilios/{id}/devolver`: JSON con `usuarioCambio`; flujo anterior sin
  observación de resolución. Para la nueva pantalla usar `resolver-novedad`.
- `PUT /domicilios/{id}/tomar`: JSON con `usuarioCambio`; conserva el flujo de
  autoasignación/reintento existente.
- `GET /domicilios/{id}`: conserva el resumen de la última novedad y auditoría.

## Preparación de base de datos

Antes de habilitar la pantalla, revisar/aplicar por empresa
`sql/alter_domicilio_resolver_novedad.sql`, que habilita las tres transiciones
usando el catálogo de estados. Ejemplo con una conexión PostgreSQL ya configurada:

```sh
psql -v empresa_id=3 -f sql/alter_domicilio_resolver_novedad.sql
```

Este cambio de código no ejecuta el script ni migra datos históricos. No requiere
crear ni poblar `domicilio_novedad`.
