-- Ejecutar por empresa con psql -v empresa_id=3 -f sql/alter_domicilio_resolver_novedad.sql
-- Habilita las tres salidas de NoEntregado. No se ejecuta desde el endpoint.
BEGIN;
INSERT INTO petalops.transicion_estado_entrega
    (empresa_id, estado_origen_id, estado_destino_id, created_at)
SELECT e.id_empresa, origen.id_estado_entrega, destino.id_estado_entrega,
       CURRENT_TIMESTAMP AT TIME ZONE 'America/Bogota'
FROM petalops.empresa e
CROSS JOIN petalops.estado_entrega origen
CROSS JOIN petalops.estado_entrega destino
WHERE e.id_empresa = :empresa_id
  AND lower(replace(origen.codigo, '_', '')) = 'noentregado'
  AND lower(replace(destino.codigo, '_', '')) IN ('entregado', 'asignado', 'pendiente')
  AND NOT EXISTS (
      SELECT 1 FROM petalops.transicion_estado_entrega t
      WHERE t.empresa_id = e.id_empresa
        AND t.estado_origen_id = origen.id_estado_entrega
        AND t.estado_destino_id = destino.id_estado_entrega
  );
COMMIT;
