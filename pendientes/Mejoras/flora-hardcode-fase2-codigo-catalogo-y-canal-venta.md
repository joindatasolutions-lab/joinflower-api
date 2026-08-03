# Logica hardcodeada de Flora — Fase 2 (codigo de catalogo configurable + canal de venta generico)

Continuacion de [flora-hardcode-fase1-limpieza-muerta.md](./flora-hardcode-fase1-limpieza-muerta.md), punto 4 de [mejoras-arquitectura.md](./mejoras-arquitectura.md).

## 1. "Mostrar codigo de catalogo" — ahora configurable por empresa

### Hallazgo: el hardcode `empresa_id == 3` estaba duplicado en 3 archivos, no 1

- `app/routers/pedido.py` (`_codigo_producto_visible`) — usado en listado de pedidos, detalle de pedido y resumen de contabilidad.
- `app/routers/domicilios.py` (`_visible_product_code` / `_product_label`, y una CASE WHEN embebida directo en SQL crudo dentro de `_listar_pedidos_disponibles_api_rows`).
- `app/routers/produccion.py` (linea suelta dentro de `_build_items`).

Los 3 hacian exactamente lo mismo: si `empresa_id == 3`, mostrar `codigo_catalogo` en vez de `codigo_producto` en listados/tickets/produccion.

### Cambio aplicado

**Nueva columna** (migracion preparada, NO ejecutada — ver mas abajo): `petalops.empresa.mostrar_codigo_catalogo BOOLEAN NOT NULL DEFAULT FALSE`. Archivo: `sql/alter_empresa_mostrar_codigo_catalogo.sql` (en el repo de `joinflower-api/sql`, no en este repo de la API). Setea `TRUE` para `empresa_id = 3` para preservar el comportamiento actual de Flora.

**Por que NO se toco el modelo ORM `Empresa`:** el documento de arquitectura ya señala (punto 6) que hay modelos ORM desincronizados con la BD real, y que una columna en el modelo que no existe aun en la tabla real rompe cualquier query ORM que la toque. Para evitar ese riesgo, el flag se lee con **SQL crudo defensivo**: primero se verifica si la columna existe (`information_schema.columns`); si no existe (migracion aun no corrida), se usa el comportamiento legado (`empresa_id == 3`) como fallback. Esto significa que el codigo ya subido es **seguro de desplegar antes de correr la migracion** — no rompe nada, simplemente sigue igual que antes hasta que la migracion se aplique.

**Nuevo helper** `_mostrar_codigo_catalogo(db, empresa_id) -> bool`, duplicado en los 3 archivos (siguiendo la convencion ya existente en el proyecto de duplicar helpers pequeños por router en vez de un modulo compartido — ej. `_activo_truthy` ya esta duplicado en `catalogo.py` y `barrios.py`).

**Performance:** el flag se calcula **una sola vez por request** (antes del loop de productos), no por cada linea de producto — se paso de recibir `empresa_id: int` a recibir `mostrar_codigo_catalogo: bool` en las funciones puras (`_codigo_producto_visible`, `_producto_listado_texto`, `_producto_listado_detalle`, `_visible_product_code`, `_product_label`). En `domicilios.py`, la consulta SQL cruda que tenia `CASE WHEN :empresa_id = 3` ahora recibe el booleano ya resuelto como bind param (`CASE WHEN :mostrar_codigo_catalogo`), sin cambiar la forma de la query.

### Como activarlo para otra empresa

Una vez corrida la migracion:
```sql
UPDATE petalops.empresa SET mostrar_codigo_catalogo = TRUE WHERE id_empresa = <id>;
```
Sin tocar codigo ni redeploy.

### Validado (sin BD real, logica pura + simulacion de sesion)

- `_codigo_producto_visible`/`_visible_product_code`/`_product_label`: probado con flag `True`/`False`, devuelve `codigo_catalogo` o `codigo_producto` segun corresponda.
- `_mostrar_codigo_catalogo` (los 3 archivos): probado con una sesion de BD simulada en dos escenarios — (a) columna no existe (migracion pendiente) devuelve el fallback legado exacto (`True` solo para empresa 3), (b) columna existe, devuelve el valor real leido, incluyendo el caso de una empresa distinta de Flora con el flag activo, y el caso de apagarlo para la propia Flora.
- Sintaxis e import completo de `app.main` verificados despues de los 3 archivos modificados.

## 2. Linea "Celular Flora" del ticket impreso — ahora usa el titulo real configurado por empresa

### Hallazgo

`sql/alter_empresa_menu.sql` confirma que **"Celular Flora" ya era un valor sembrado** (`titulo`) en `petalops.empresa_menu` para el campo `pedido_canal_venta` de Flora — el sistema de configuracion por empresa (`empresa_menu`, ya usado activamente para metodos de pago y canal de venta) ya soportaba esto. El codigo de impresion del ticket (`pedido.py`) no lo estaba usando: tenia el texto "Celular Flora" hardcodeado y el gate `if empresa_id == FLORA_EMPRESA_ID`, ignorando el titulo real configurado en BD.

### Cambio aplicado (`app/routers/pedido.py`, funcion `descargar_factura_pedido`)

- Se carga `canal_venta_field = _load_empresa_menu_config(db, empresa_id=...).get("pedido_canal_venta")` — la misma config que ya se usaba para las validaciones de aprobacion.
- La linea del ticket ahora es `f"{canal_venta_field['titulo']}: {valor}"`, y solo se imprime si `canal_venta_field` existe y esta activo para esa empresa (ya viene filtrado `activo = TRUE` desde `_load_empresa_menu_rows`). Cualquier empresa que configure su propio canal de venta vera la linea con SU titulo, no con el de Flora.
- Se corrigieron ademas dos mensajes de error relacionados que tenian el mismo problema (hardcodeaban "Celular Flora" / "Flora" en vez de usar `channel_field['titulo']`, que ya estaba cargado ahi mismo): `FLORA_CHANNEL_REQUIRED` y `FLORA_CHANNEL_INVALID` en el endpoint de actualizacion de pago del pedido.

### Que NO se toco

- El nombre interno del campo (`canalFlora` en el schema `PedidoManualRequest`/`payload.canalFlora`, y la key `"canalFlora"` en las respuestas de pago) sigue igual — es un contrato de API que probablemente ya consume el frontend. Renombrarlo es un cambio cruzado con el frontend, fuera del alcance de esta fase.
- Los codigos de error (`FLORA_CHANNEL_REQUIRED`, `FLORA_CHANNEL_INVALID`) tampoco se renombraron, mismo motivo.

## Pendiente (no tocado en esta fase)

El subtitulo "Tienda de Flores" en `_factura_empresa_labels` (linea ~185, `if empresa_id == FLORA_EMPRESA_ID`) sigue igual — no fue parte de lo pedido en esta fase.

## Antes de que esto tenga efecto en produccion

El codigo ya desplegado es seguro (fallback legado si la migracion no corrio), pero **para que otras empresas puedan activar "mostrar codigo de catalogo"**, hay que correr manualmente `sql/alter_empresa_mostrar_codigo_catalogo.sql` contra la base de datos. Esto NO se ejecuto — queda a criterio y decision del usuario, siguiendo el mismo flujo manual que ya usan para las demas migraciones en `sql/`.
