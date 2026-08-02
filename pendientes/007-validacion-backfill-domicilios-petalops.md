# Pendiente 007 - Validacion y backfill de domicilios Petalops

## Hallazgos

- Petalops tiene catalogo `estado_entrega` completo: pendiente, asignado, en_ruta, entregado, no_entregado, cancelado.
- `transicion_estado_entrega` tenia las transiciones principales, pero faltaban reglas para devolver a pendiente: `asignado -> pendiente` y `no_entregado -> pendiente`.
- `entrega` para Petalops no presenta pedidos invalidos, estados invalidos ni producciones invalidas.
- Hay entregas historicas sin `domicilio_auditoria`; esto afecta trazabilidad, no el estado operativo actual.
- En back, algunas rutas cambiaban estado sin auditoria: asignacion administrativa y toma/reintento por domiciliario.

## Decision segura

- No cambiar estados actuales de entregas.
- No crear entregas faltantes salvo que se detecte una brecha funcional explicita y se valide aparte.
- Poblar solamente transiciones faltantes e insertar auditoria sintetica para entregas sin auditoria.
- Ejecutar laboratorio con rollback usando usuario/domiciliario de Petalops, no Flora.

## Cambios tecnicos asociados

- `app/services/domicilio_service.py`: defaults de transicion incluyen devoluciones a pendiente y el seeding automatico inserta faltantes idempotentes.
- `app/routers/domicilios.py`: asignar, tomar y reintentar entrega registran `domicilio_auditoria`.
- `sql/seed_transicion_estado_entrega_defaults.sql`: agrega `asignado -> pendiente` y `no_entregado -> pendiente`.
- `scripts/backfill_domicilio_auditoria_historica.py`: backfill seguro, solo inserta auditoria historica.

## Validaciones requeridas

- Dry-run del backfill antes de aplicar.
- Aplicar backfill solo para `empresa_id = 2`.
- Laboratorio completo pedido -> produccion -> domicilio dentro de transaccion con rollback.
- Tests de domicilios y compilacion Python.
## Ejecucion realizada

- Se insertaron 2 transiciones faltantes para Petalops: `asignado -> pendiente` y `no_entregado -> pendiente`.
- Dry-run de backfill detecto 41 entregas sin auditoria.
- Backfill aplicado para `empresa_id = 2`: 41 filas `CREAR_ENTREGA_HISTORICA` en `domicilio_auditoria`.
- Validacion posterior: 0 entregas Petalops sin auditoria.
- Conteos de entregas por estado no cambiaron despues del backfill.

## Laboratorio rollback

- Pedido temporal: 3288.
- Produccion temporal: 3131.
- Entrega temporal: 3263.
- Flujo validado: checkout -> aprobar -> asignar produccion -> EnProduccion -> ParaEntrega -> tomar entrega -> EnRuta -> Entregado.
- Auditoria de domicilio dentro de la transaccion: `AUTOASIGNACION`, `EN_RUTA`, `ENTREGADO`.
- Rollback confirmado: pedido, produccion, entrega y auditorias del laboratorio no existen despues del rollback.
- Conteos antes y despues del rollback quedaron iguales: pedidos 56, producciones 36, entregas 56, domicilio_auditoria 88.