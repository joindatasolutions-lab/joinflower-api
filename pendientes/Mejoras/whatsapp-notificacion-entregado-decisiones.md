# Decisiones de diseño — notificacion WhatsApp al marcar pedido ENTREGADO

Companion de [promt-meta.md](./promt-meta.md) (el pedido original). Este documento registra que se decidio implementar realmente, basado en el analisis del codigo/BD real hecho antes de escribir codigo (seccion 19 del pedido original), y por que se desvia en algunos puntos de lo literal del pedido.

**Rama**: `feature/whatsapp-notificacion-entregado`, separada de `main`. Nada de esto llega a produccion hasta que se decida desplegar explicitamente.

## Hallazgo que cambio el diseño: Pedido nunca llega a ENTREGADO hoy

Se esperaba enganchar la notificacion a "el pedido pasa a ENTREGADO". Se encontro que **eso no ocurre nunca en el flujo real**:

- `Pedido.estadoPedidoID` solo se modifica en 4 lugares de todo el codigo (creacion, aprobar, rechazar, y el endpoint generico de cambio de estado) — ninguno apunta a ENTREGADO.
- Validado contra la BD real: el catalogo `estado_pedido` tiene una fila ENTREGADO (`id_estado_pedido=20`) pero esta marcada `activo=0`, y **no existe ninguna transicion configurada, para ninguna empresa,** en `transicion_estado_pedido` que permita llegar a ese estado.
- Aun asi hay 16 pedidos de Flora ya en `estado_pedido_id=20` — llegaron ahi por fuera del flujo validado de la app (manual o codigo legado), no es algo que la app haga hoy de forma consistente.
- El evento real, consistente y activo de "se entrego" es `Entrega.estadoEntregaID` llegando a ENTREGADO — Flora tiene 3,719 pedidos y 3,718 entregas, practicamente 1 a 1, confirmando que el tracking real de entregas vive en `Entrega`, no en `Pedido`.

**Decision**: el disparador de la notificacion es exclusivamente `Entrega.estadoEntregaID -> ENTREGADO`, dentro de `_marcar_entregado_impl()` (`app/routers/domicilios.py`), el unico lugar del codigo donde esto ocurre (dos rutas HTTP distintas ya convergen ahi). **No se toca `Pedido.estadoPedidoID` para nada** — resucitar automaticamente un estado que el equipo desactivo deliberadamente, sin ninguna regla de transicion que lo respalde, seria ir en contra de una decision de diseño existente y agregar riesgo sin necesidad real.

## Aislamiento multi-tenant: por que el chequeo explicito no es opcional

Se valido que **ninguna** de las tablas `pedido`, `entrega`, `cliente` tiene una llave foranea real en Postgres (ni siquiera `pedido -> cliente`), pese a que el modelo ORM en Python si las declara. Es decir, la base de datos no tiene ningun freno automatico contra un cruce de datos entre empresas — la unica proteccion real es la que se agregue en el codigo de la aplicacion.

Se confirmo tambien, contra datos reales, que **hoy no existe contaminacion cruzada** (0 pedidos con cliente de otra empresa, 0 huerfanos, 0 entregas con pedido de otra empresa) — pero ya hubo un precedente de este tipo de error en este mismo codebase: antes de mapear correctamente `Empresa.nombreComercial`, las facturas de **todas** las empresas mostraban "FLORA" por un valor por defecto sin resolver (ver comentario en `app/models/empresa.py:12-13`). Esto confirma que el chequeo explicito de tenant que pide el documento original no es paranoia — es la unica barrera real disponible.

**Decision**: se implementa tal como pide el documento original — las 3 consultas (Pedido, Cliente, Empresa) siempre filtradas por `empresa_id` en el mismo `WHERE`, mas una verificacion explicita final (`if`, no `assert`) de `pedido.empresa_id == cliente.empresa_id == empresa.id` antes de enviar, registrando `SECURITY_TENANT_MISMATCH` y abortando si falla.

## Arquitectura: archivos planos, no subpaquete

El documento original sugiere `services/whatsapp/` (con `client.py`, `service.py`, `schemas.py`, `exceptions.py`). El codigo existente (`domicilio_service.py`, `pedido_service.py`, `produccion_service.py`, etc.) usa siempre archivos planos en `app/services/`, sin subcarpetas ni clases de servicio — solo funciones a nivel de modulo.

**Decision**: se sigue la convencion existente — `app/services/whatsapp_service.py` (reglas de negocio) y `app/services/whatsapp_client.py` (solo HTTP a Meta), sin subpaquete.

## Trabajo en segundo plano: se reutiliza el patron del job de produccion existente

`app/jobs/produccion_autoassign_job.py` ya resuelve exactamente el mismo problema (trabajo en segundo plano fuera del ciclo de una peticion HTTP, con su propia sesion de BD y proteccion contra ejecucion duplicada via `pg_advisory_lock` de Postgres). No hay Celery, RQ ni APScheduler en este proyecto.

**Decision**: `app/jobs/whatsapp_dispatch_job.py` sigue el mismo patron (thread + advisory lock con una clave nueva y distinta), en vez de introducir un sistema de colas nuevo.

## Idempotencia

`UNIQUE (empresa_id, pedido_id, evento, canal)` + `INSERT ... ON CONFLICT DO NOTHING`, insertado en la **misma transaccion** que el cambio de `Entrega.estadoEntregaID` a ENTREGADO. Mismo patron ya usado en `token_revocado` (revocacion de tokens JWT) — la garantia real es la restriccion UNIQUE a nivel de base de datos, no una lectura-antes-de-escribir en la aplicacion (que si podria fallar ante condiciones de carrera).

## Bug preexistente encontrado, sin relacion con esta funcionalidad

`requirements.txt` tiene `httpx2` en vez de `httpx` — un paquete que no existe. No hay ningun cliente HTTP saliente en el proyecto hoy; se corrige como parte de este trabajo porque es indispensable para poder llamar a la API de Meta, pero es un bug preexistente, no introducido por esta funcionalidad.

## Que NO cambia con esta funcionalidad

- `Pedido.estadoPedidoID` y su maquina de estados: intacta.
- Ninguna tabla existente (`pedido`, `cliente`, `entrega`, etc.) se modifica en su estructura ni en sus datos.
- El flujo de marcar una entrega como entregada (`PUT /domicilios/{id}/entregado`) sigue funcionando exactamente igual si WhatsApp falla o no esta configurado — nunca se revierte la entrega por un fallo de notificacion.

## Seguridad del despliegue

1. Todo el trabajo se hace en la rama `feature/whatsapp-notificacion-entregado`, nunca directo en `main`.
2. La tabla nueva (`whatsapp_notificacion`) se crea con un script en `sql/`, ejecutado manualmente por el usuario via DBeaver — igual que el indice de Domicilios. No se ejecuta ninguna escritura automatica contra la base de datos de produccion desde esta sesion.
3. Nada se despliega a Cloud Run sin confirmacion explicita del usuario.
4. Mientras META_WHATSAPP_ACCESS_TOKEN / META_WHATSAPP_PHONE_NUMBER_ID no esten configurados, el intento de envio falla de forma controlada (queda en la tabla como FAILED/SKIPPED) sin afectar el flujo de entrega — se puede desplegar el codigo antes de tener las credenciales reales de Meta listas, sin riesgo.
