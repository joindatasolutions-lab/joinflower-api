# Pendiente 002 - Backfill historico de pedidos

## Objetivo
Completar trazabilidad y produccion historica faltante sin contaminar datos actuales.

## No ejecutar sin aprobacion
Estos backfills deben revisarse por empresa y por rango de fechas antes de correr en produccion.

## 1. Pedidos aprobados sin produccion
Validar primero:

```sql
SELECT p.empresa_id, COUNT(*) AS total
FROM petalops.pedido p
JOIN petalops.estado_pedido ep ON ep.id_estado_pedido = p.estado_pedido_id
WHERE UPPER(TRIM(ep.nombre_estado)) = 'APROBADO'
  AND NOT EXISTS (
    SELECT 1
    FROM petalops.produccion pr
    WHERE pr.pedido_id = p.id_pedido
      AND pr.empresa_id = p.empresa_id
  )
GROUP BY p.empresa_id
ORDER BY p.empresa_id;
```

Decision requerida:
- Crear produccion solo para pedidos aprobados recientes y aun vigentes.
- No crear produccion para pedidos ya entregados/cancelados operativamente.
- Validar fecha de entrega y detalle antes de generar produccion.

## 2. Pedidos sin auditoria
Validar primero:

```sql
SELECT p.empresa_id, COUNT(*) AS total
FROM petalops.pedido p
WHERE NOT EXISTS (
  SELECT 1
  FROM petalops.pedido_auditoria pa
  WHERE pa.pedido_id = p.id_pedido
    AND pa.empresa_id = p.empresa_id
)
GROUP BY p.empresa_id
ORDER BY p.empresa_id;
```

Backfill recomendado:
- Insertar solo evento sintetico `CREAR_PEDIDO_HISTORICO`.
- Usar `actor_login = 'system.backfill'`.
- Usar `estado_destino_id = pedido.estado_pedido_id` si no se puede reconstruir el estado inicial real.
- No inventar aprobaciones/cancelaciones si no hay evidencia en logs o tablas relacionadas.

## 3. Criterio de seguridad
Primero ejecutar consultas de conteo y muestreo por empresa. Luego crear scripts idempotentes por empresa, con `WHERE NOT EXISTS` y transaccion controlada.