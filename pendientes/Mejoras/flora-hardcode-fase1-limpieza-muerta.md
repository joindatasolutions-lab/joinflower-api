# Logica hardcodeada de Flora (empresa 3) — Fase 1 (limpieza de codigo muerto)

Relacionado con el punto 4 de [mejoras-arquitectura.md](./mejoras-arquitectura.md) ("Lógica hardcodeada para empresa específica (Flora = empresa 3)").

## Hallazgo: el problema descrito en el documento ya no aplica en su mayor parte

El fix que el documento sugeria ("mover metodos de pago a `metodo_pago_catalogo`, reglas de aprobacion a config por empresa") **ya estaba implementado** en el codigo, aparentemente por trabajo posterior a cuando se escribio el documento:

- `metodo_pago_catalogo` y `canal_venta`: tablas reales por empresa, sincronizadas a `empresa_menu` via `app/services/empresa_menu_service.py`. Usadas activamente en mas de 10 lugares de `pedido.py`.
- `_tenant_order_rules(db, empresa_id)` (pedido.py, ahora unica definicion): lee `require_payment_before_approval` / `require_sales_channel_before_approval` desde `empresa_menu` (config real por empresa), no desde un hardcode de Flora.

Como consecuencia, existia una **version vieja y hardcodeada de la misma funcion** (`_tenant_order_rules(empresa_id)`, sin `db`) definida ANTES en el archivo, que Python sobrescribia silenciosamente con la version nueva (misma nombre, mas abajo). Esa version vieja nunca se ejecutaba — era codigo muerto.

## Cambio aplicado en esta fase

Se elimino de `app/routers/pedido.py` (antes de la funcion `_activo_truthy`):

- `FLORA_PAYMENT_METHODS` (set de ~24 metodos de pago hardcodeados) — sin ninguna referencia en el resto del codigo.
- `FLORA_SALES_CHANNELS` (set de canales de venta hardcodeados) — sin ninguna referencia en el resto del codigo.
- La primera definicion de `_tenant_order_rules(empresa_id)` (la que usaba `FLORA_EMPRESA_ID` directamente) — shadowed/inalcanzable, reemplazada por la version en base a `db` + `empresa_menu`.

**Cero cambio de comportamiento**: se confirmo que ninguna de las tres piezas se ejecutaba en producción (grep en todo `app/` no encontro otras referencias), asi que remover el codigo no afecta ningun endpoint. Se valido sintaxis y que `app.main` (la app completa) sigue importando sin errores.

Se dejaron intactos: `FLORA_EMPRESA_ID` (si sigue en uso, ver fase 2), `STORE_PICKUP_DELIVERY_VALUES`, `LINK_PAYMENT_METHODS`, `LINK_SURCHARGE_PCT` — esos si tienen referencias activas en el archivo.

## Lo que queda pendiente (Fase 2 — requiere decision de producto, no solo codigo)

Tres usos reales y activos de `FLORA_EMPRESA_ID` que quedan, todos en la generacion de PDF/tickets de pedido (no en logica de negocio critica ni en aprobaciones):

1. **`pedido.py` (`_factura_empresa_labels`)**: si el nombre de la empresa no trae subtitulo, y `empresa_id==3`, usa "Tienda de Flores" como subtitulo fijo en la factura PDF.
2. **`pedido.py` (`_codigo_producto_visible`)**: si `empresa_id==3` (literal `3`, sin usar la constante), muestra `codigoCatalogo` en vez de `codigoProducto` en tickets/recibos impresos.
3. **`pedido.py` (linea del ticket impreso)**: solo si `empresa_id==3`, agrega la linea "Celular Flora: {canal}" (dato que en realidad viene de `_petalopsMetadata.canalFlora` del pago, nombrado especificamente para Flora).

Pendiente de decidir con el usuario antes de tocar: si estos 3 puntos deben volverse configurables por empresa (nuevo campo en `empresa` o `empresa_menu`) o si se dejan como estan porque hoy solo Flora los necesita.
