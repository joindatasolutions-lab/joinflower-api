# PENDIENTE — Pipeline oculta pedidos activos creados en dias anteriores

**Estado: diagnosticado (2026-08-11), NO corregido todavia.** Requiere confirmar con el negocio (Flora / equipo Petalops) cual debe ser el comportamiento correcto antes de tocar el filtro, porque afecta a todos los tenants, no solo a uno.

Reportado como "a Flora no le aparecen los pedidos en el pipeline en tiempo actual, en cambio a mi si" — se investigo como posible bug de zona horaria (PC del reportante en horario Chile vs Colombia) y **se descarto esa hipotesis**: `todayIsoDateBogota()` en el frontend ya calcula "hoy" siempre en `America/Bogota` via `Intl.DateTimeFormat` con `timeZone` explicito, sin importar el reloj/zona horaria del sistema operativo del cliente. Ademas, al momento del reporte (2026-08-11 ~12:07pm hora Bogota) Chile y Colombia coincidian en la fecha calendario, asi que un desfase de zona horaria no podia estar causando el sintoma en ese momento.

## Causa raiz real (validada con codigo + logs de produccion)

- El endpoint `GET /pipeline/pedidos` (`app/routers/pipeline.py`, funcion `listar_pipeline_pedidos`, filtro alrededor de la linea 294) filtra **todo** el resultado por `Pedido.fechaPedido` (columna `fecha_pedido`, la fecha en que se **creo** el pedido) usando el rango `fechaDesde`/`fechaHasta`/`fecha`/`soloHoy` que manda el frontend.
- El frontend (`pipelineConfig.jsx`, `INITIAL_FILTERS`) inicializa `fechaDesde = fechaHasta = todayIsoDateBogota()` **por defecto** cada vez que se abre la pestana Pipeline.
- Resultado: un pedido creado AYER que sigue "Pendiente/En produccion" o "Listo" (todavia no entregado ni cancelado) **desaparece del tablero por defecto**, porque su `fecha_pedido` no cae dentro del rango "hoy" — aunque siga totalmente activo y relevante para la operacion de hoy.
- Confirmado en logs reales de Cloud Run (`join-flower`, 2026-08-11 ~16:21 UTC): alguien amplio manualmente el filtro a `fechaDesde=2026-08-10&fechaHasta=2026-08-11` (2 dias) para poder ver mas pedidos — coincide exactamente con el patron "a mi si me aparecen, a Flora no", porque Flora estaba usando el filtro por defecto (solo hoy) sin saber que hacia falta ampliarlo.

## Por que importa

El tab "Pipeline" esta pensado como tablero de trabajo en vivo (existen tabs separados "Historial reasignaciones" y "Historial pedidos" para consultas historicas por fecha). Que el tablero en vivo oculte trabajo activo de dias anteriores por un filtro de fecha de creacion es, en la practica, un bug funcional: el personal puede pensar que un pedido "desaparecio" o que no hay nada pendiente cuando en realidad si lo hay, solo que fue creado antes de hoy (muy comun en floristeria: pedido tomado en la tarde para entrega temprano al dia siguiente).

## Opciones evaluadas (pendiente decision del negocio)

1. **Mostrar todo lo activo sin filtro de fecha, acotar solo Entregado/Cancelado por fecha** (recomendada tecnicamente, comportamiento tipico de un tablero Kanban): las columnas Creado/Aprobado/Pendiente-Produccion/En-produccion/Listo/En-camino se muestran siempre hasta que se entregan o cancelan; Entregado y Cancelado si se acotan a la fecha seleccionada (por defecto hoy) para que esas columnas no crezcan sin limite.
2. **Mantener el filtro por fecha, pero avisar** cuando hay pedidos activos fuera del rango visible (ej. "hay N pedidos activos de dias anteriores, amplia el filtro para verlos"), sin cambiar el comportamiento base.
3. No tocar nada por ahora (opcion elegida por el momento, 2026-08-11) — solo queda documentado el hallazgo.

## Siguiente paso

Confirmar con el usuario/negocio cual de las opciones anteriores refleja como debe funcionar el Pipeline, antes de modificar `app/routers/pipeline.py` (filtro de fecha) y/o `pipelineConfig.jsx` (`INITIAL_FILTERS`) en el frontend.
