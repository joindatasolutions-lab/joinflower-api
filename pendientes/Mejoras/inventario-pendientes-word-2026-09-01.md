# Pendientes Inventario - Word 2026-09-01

Implementado y validado, sin migraciones destructivas:

- Metricas por categoria en `GET /inventario/metricas`.
- Catalogos operativos por categoria en `GET /inventario/categorias`.
- Registro explicito de compras en `POST /inventario/compras`.
- Historial formal de compras en `GET /inventario/compras`, reutilizando `petalops.movimiento_inventario`.
- Registro explicito de danos/perdidas en `POST /inventario/danos`.
- Evidencia fotografica de danos en `movimiento_inventario.evidencia_url`.
- Filtros extendidos y campos de lectura para movimientos en `GET /inventario/movimientos`.
- Metricas de movimientos en `GET /inventario/movimientos/metricas`.
- Stock anterior/nuevo por movimiento en `movimiento_inventario.stock_anterior` y `stock_nuevo`.
- Anulacion de movimientos con reverso auditado en `POST /inventario/movimientos/{movimientoID}/anular`.
- PDF/impresion de movimientos en `GET /inventario/movimientos/{movimientoID}/pdf`.
- Control automatico de cupos por pedidos contra recetas con `capacidad_manual`, aplicado en checkout, pedido manual, pedido legacy y aprobacion de pedidos.
- Panel basico de consulta de inventario en el frontend de pruebas local.
- Frontend productivo en `C:\Users\CAA4746\Documents\JOIN\Arquitectura\Petalops_Modulos-main\Petalops_Modulos-main`: cliente API, catalogos de inventario, acciones por item, formulario unico de movimientos, filtros, tabla extendida de movimientos, acciones de PDF y anulacion.
- Validacion de BD: se reutilizan `petalops.insumo`, `petalops.inventario`, `petalops.movimiento_inventario`, `petalops.proveedor`, `petalops.receta` y tablas existentes de pedidos; no se crearon tablas nuevas.
- Migracion aplicada en BD: `sql/alter_inventario_movimientos_auditoria.sql`.

Pendientes funcionales del archivo:

- Ninguno abierto en backend para las instrucciones listadas.
- Validaciones ejecutadas: `python -m compileall app`, `python -m pytest tests\test_inventario_catalogos.py` y `npm run build` en el frontend productivo.
