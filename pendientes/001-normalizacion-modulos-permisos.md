# Pendiente 001 - Normalizacion de modulos y permisos

## Contexto

Antes de entrar a produccion se detecto que el sistema no tiene una fuente unica de verdad para los modulos. El back compone el acceso desde varias tablas y tambien desde listas hardcodeadas, mientras el front usa una lista de navegacion parcialmente distinta.

Tablas involucradas:

- `modulo` o tabla maestra equivalente: actualmente falta como fuente canonica clara.
- `plan_modulo`: modulos incluidos por plan comercial.
- `empresa_modulo`: override de activacion por empresa.
- `permiso_modulo`: permisos por rol y modulo.
- `usuario_modulo`: restriccion fina por usuario.

## Problema

Ninguna tabla contiene por si sola la lista oficial completa de modulos. Ademas, hay diferencias entre modulos visuales del front y permisos reales del back.

Ejemplos detectados:

- `barrios` aparece como modulo/pantalla en front, pero el back protege endpoints de barrios con `domicilios` o `pedidos`.
- `clientes` aparece como modulo en front, pero el back protege endpoints de clientes con `pedidos`.
- `pipeline` aparece como modulo, pero el front lo habilita por rol admin/global y el back lo protege con `pedidos`.
- `trazabilidad` aparece en front/BD, pero no queda claro como modulo de negocio independiente.
- `usuarios` se maneja mas como panel administrativo por rol que como modulo normal.
- `empresa_modulo.activo` en BD es `integer`, pero el back intenta escribir boolean.

## Modulos canonicos propuestos

Lista recomendada para produccion:

- `pipeline`
- `pedidos`
- `produccion`
- `domicilios`
- `barrios`
- `inventario`
- `catalogo`
- `clientes`
- `contabilidad`
- `reportes`
- `usuarios`

Decision sugerida:

- No dejar `trazabilidad` como modulo canonico por ahora.
- Tratar trazabilidad como funcionalidad interna de `pedidos`, `pipeline` o auditoria.
- Si mas adelante existe una pantalla formal de auditoria/trazabilidad con reglas propias, reabrir el analisis y convertirlo en modulo canonico.

## Modelo recomendado

Crear o consolidar una tabla maestra `modulo` con:

- `codigo`
- `nombre`
- `descripcion`
- `orden`
- `activo`
- `es_navegable`

Luego aplicar esta responsabilidad:

- `modulo`: catalogo oficial y unico de modulos.
- `plan_modulo`: define que modulos trae cada plan.
- `empresa_modulo`: activa/desactiva modulos para una empresa especifica.
- `permiso_modulo`: define acciones permitidas por rol.
- `usuario_modulo`: limita el acceso final del usuario.

## Regla de acceso esperada

Un usuario puede acceder a un modulo solo si:

1. El modulo existe en `modulo` y esta activo.
2. El modulo esta disponible para el plan o habilitado por empresa.
3. El rol tiene permiso para la accion solicitada.
4. El usuario no tiene el modulo desactivado por override.

## Acciones tecnicas sugeridas

1. Crear migracion para tabla `modulo`.
2. Poblar `modulo` con la lista canonica.
3. Normalizar `empresa_modulo.activo` a boolean o ajustar el back a `1/0`.
4. Alinear `DEFAULT_MODULES` del back con la lista canonica o eliminarlo como fuente de verdad.
5. Cambiar protecciones del back:
   - `/barrios` debe usar modulo `barrios`.
   - `/clientes` debe usar modulo `clientes`.
   - `/pipeline` debe usar modulo `pipeline`, si se quiere manejar como modulo real.
6. Alinear el sidebar del front con la respuesta del back.
7. Impedir que el front asigne a un usuario modulos no activos para su empresa.
8. Agregar tests de acceso por empresa, rol y usuario.

## Validaciones antes de ejecutar

- Confirmar lista final de modulos con negocio.
- Confirmar si `contabilidad` queda como modulo oficial.
- Confirmar si `reportes` sera modulo visible o solo permiso interno.
- Confirmar si `catalogo` sera pantalla visible o permiso auxiliar usado por pedidos/inventario.
- Confirmar si `trazabilidad` se elimina como modulo o se conserva como subfuncion.

## Estado

Pendiente de aprobacion para implementacion.
