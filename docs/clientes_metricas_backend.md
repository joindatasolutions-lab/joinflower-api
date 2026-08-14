# Metricas de clientes

## Entrega 1

Endpoints:

- `GET /tenants/{tenant_id}/customers/metrics`
- `GET /tenants/{tenant_id}/customers/segments`
- `GET /tenants/{tenant_id}/customers/opportunities`
- `GET /clientes?includeMetrics=true`

Cubre:

- base de clientes: total, compradores, sin compras, nuevos, recurrentes y tasa de recompra
- actividad: activos 30/60/90 dias, inactivos y en riesgo
- valor: facturacion del periodo, ticket promedio, valor promedio por cliente, VIP y porcentaje de revenue recurrente
- frecuencia: compras promedio por cliente y dias promedio entre compras
- segmentos multiples por cliente: `NEW`, `ACTIVE`, `RECURRING`, `VIP`, `INACTIVE`, `AT_RISK`, `HIGH_VALUE`
- oportunidades por fechas especiales: cumpleanos y aniversarios

## Entrega 2

Endpoints nuevos o ampliados:

- `GET /tenants/{tenant_id}/customers/{customer_id}/metrics`
- `GET /tenants/{tenant_id}/customers/segments?sort=lifetime_value`
- `GET /clientes?includeMetrics=true`

Cubre:

- LTV historico por cliente como `lifetime_value`
- facturacion historica del tenant como `value.lifetime_revenue`
- valor promedio historico por cliente como `value.average_lifetime_value`
- producto favorito por cliente como `favorite_product`
- categoria favorita por cliente como `favorite_category`
- rango promedio de precio por cliente como `average_price_range`
- canal preferido por cliente como `preferred_channel`
- `preferred_occasion` se devuelve como `null` porque no hay una fuente confiable de ocasion en pedidos
- oportunidades enriquecidas con `lifetime_value`, `favorite_product`, `favorite_category` y `preferred_channel`
- detalle directo de metricas de un cliente sin cargar todo el listado

## Entrega 3

Endpoints nuevos o ampliados:

- `GET /tenants/{tenant_id}/customers/intelligence`
- `GET /tenants/{tenant_id}/customers/priorities`
- `GET /tenants/{tenant_id}/customers/metrics`
- `GET /tenants/{tenant_id}/customers/{customer_id}/metrics`
- `GET /clientes?includeMetrics=true`

Cubre:

- `customer_health_score` por cliente, escala 0 a 100
- `churn_risk_probability` por cliente, escala 0 a 100
- `repurchase_probability` por cliente, escala 0 a 100
- `next_best_action` centralizado en backend
- resumen agregado en `metrics.intelligence`
- insights textuales accionables en `metrics.insights`
- listado de clientes por inteligencia comercial
- prioridad comercial por cliente como `commercial_priority` y `commercial_priority_label`
- resumen agregado por prioridad en `metrics.commercial_priorities`
- listado de clientes por prioridad comercial
- filtros de inteligencia por:
  - `action`
  - `risk=HIGH|LOW`
  - `min_health_score`
  - `max_health_score`
- ordenamiento por:
  - `customer_health_score`
  - `churn_risk_probability`
  - `repurchase_probability`

Acciones iniciales:

- `ACQUIRE_FIRST_PURCHASE`
- `SPECIAL_DATE_CAMPAIGN`
- `REACTIVATE`
- `VIP_CARE`
- `REORDER_FAVORITE`
- `WELCOME_SECOND_PURCHASE`
- `NURTURE`

Notas:

- Esta entrega usa scoring heuristico, no un modelo ML entrenado.
- La logica esta centralizada en backend para que frontend no replique reglas criticas.
- Las probabilidades son indicadores operativos comparables entre clientes del mismo tenant.

## Parametros comunes

- `start_date`: fecha inicial opcional, formato `YYYY-MM-DD`
- `end_date`: fecha final opcional, formato `YYYY-MM-DD`
- `comparison=true`: disponible en metricas principales cuando hay periodo explicito
- `page`, `limit`: paginacion en segmentos, prioridades y oportunidades
- `search`: busqueda por nombre, identificacion, telefono o email en segmentos y prioridades
- `priority`: filtro de prioridad comercial en `/customers/priorities`, valores `P0` a `P8`
- `sort`: `name`, `last_purchase_at`, `first_purchase_at`, `purchase_count`, `total_spent`, `lifetime_value`, `average_order_value`, `average_price_range`, `days_since_last_purchase`, `average_days_between_purchases`, `favorite_product`, `favorite_category`, `preferred_channel`, `commercial_priority`
- `order`: `asc` o `desc`

## Insights

`GET /tenants/{tenant_id}/customers/metrics` devuelve `insights`.

Ejemplo:

```json
[
  {
    "code": "CUSTOMERS_AT_RISK",
    "message": "173 clientes estan en riesgo de abandono.",
    "metric": "activity.at_risk",
    "value": 173,
    "segment": "AT_RISK"
  }
]
```

Los insights no reemplazan los datos base; solo son mensajes respaldados por metricas y segmentos.

## Endpoint de inteligencia

```http
GET /tenants/{tenant_id}/customers/intelligence?action=REACTIVATE&risk=HIGH&page=1&limit=50
```

Respuesta:

```json
{
  "total": 173,
  "page": 1,
  "limit": 50,
  "data": [
    {
      "customer_id": "123",
      "name": "Maria Perez",
      "lifetime_value": 1850000,
      "customer_segment": ["VIP", "RECURRING", "AT_RISK"],
      "segments": ["VIP", "RECURRING", "AT_RISK"],
      "commercial_priority": "P0",
      "commercial_priority_label": "VIP en riesgo",
      "intelligence": {
        "customer_health_score": 42.5,
        "churn_risk_probability": 85,
        "repurchase_probability": 15,
        "next_best_action": {
          "action": "REACTIVATE",
          "message": "Cliente con senales de abandono. Enviar incentivo o contacto personalizado.",
          "recommended_product": "Ramo premium",
          "recommended_category": "Rosas",
          "preferred_channel": "WhatsApp"
        }
      }
    }
  ]
}
```

## Endpoint de prioridades comerciales

```http
GET /tenants/{tenant_id}/customers/priorities?priority=P0&page=1&limit=50
```

Respuesta:

```json
{
  "priority": "P0",
  "label": "VIP en riesgo",
  "total": 23,
  "total_historical_value": 42800000,
  "page": 1,
  "limit": 50,
  "data": [
    {
      "customer_id": "123",
      "segments": ["VIP", "RECURRING", "AT_RISK"],
      "commercial_priority": "P0",
      "commercial_priority_label": "VIP en riesgo",
      "purchase_count": 8,
      "total_spent": 2850000,
      "last_purchase_at": "2026-04-10",
      "days_since_last_purchase": 126
    }
  ]
}
```

## Reglas de negocio

- Todas las consultas filtran por `empresa_id` y validan tenant contra el usuario autenticado.
- Solo los pedidos con estado `APROBADO` cuentan como compra efectiva.
- Pedidos en estado `CREADO` no cuentan como compra, revenue, recurrencia, actividad, favoritos ni preferencias. Un cliente que solo tenga pedidos `CREADO` se considera `non_buyer`.
- Clientes cuyo `nombre_completo` contenga `prueba` se excluyen de las metricas, segmentos, oportunidades e inteligencia de clientes. La comparacion no distingue mayusculas/minusculas, por lo que nombres como `PRUEBA` o `pruebammmm` no entran en los indicadores.
- Un cliente puede pertenecer a varios segmentos. `segments` representa caracteristicas del cliente; no es una categoria unica.
- `commercial_priority` representa la prioridad de accion comercial y se calcula desde `segments`.
- Prioridad comercial: `P0 = VIP + AT_RISK`, `P1 = HIGH_VALUE + AT_RISK`, `P2 = AT_RISK`, `P3 = VIP + INACTIVE`, `P4 = HIGH_VALUE + INACTIVE`, `P5 = INACTIVE`, `P6 = NEW`, `P7 = RECURRING`, `P8 = ACTIVE`.
- Labels: `P0 VIP en riesgo`, `P1 Alto valor en riesgo`, `P2 Cliente en riesgo`, `P3 VIP inactivo`, `P4 Alto valor inactivo`, `P5 Cliente inactivo`, `P6 Cliente nuevo`, `P7 Cliente recurrente`, `P8 Cliente activo`.
- `VIP` es top 10% historico por `total_spent`.
- `HIGH_VALUE` es top 20% historico por `total_spent`.
- `AT_RISK` aplica solo a clientes con 2 o mas compras cuando `days_since_last_purchase > average_days_between_purchases * 1.5`.
- Preferencias se calculan con compras historicas validas.
- `customer_health_score` combina recencia, frecuencia y valor, penalizando clientes `AT_RISK`.
- `churn_risk_probability` compara recencia contra frecuencia historica cuando hay suficientes compras; si no, usa ventanas de inactividad.
- `repurchase_probability` es una senal heuristica inversa al churn, ajustada por actividad y recurrencia.
- `average_price_range` usa umbrales backend iniciales: `LOW <= 120000`, `MID <= 250000`, `HIGH > 250000`.
- `preferred_occasion` no se infiere mientras no exista un campo confiable de ocasion en pedidos.

## Performance

Script agregado:

- `sql/alter_cliente_metricas_indexes.sql`

Incluye indices para:

- `cliente(empresa_id, cliente_id)`
- `pedido(empresa_id, cliente_id, fecha_pedido, estado_pedido_id)`
- `pedido_detalle(empresa_id, pedido_id, producto_id)`
- `pedido_canal_venta(empresa_id, pedido_id)`
- `producto(empresa_id, categoria_id, id_producto)`

Para volumen alto, evaluar ejecutar estos indices en una ventana controlada y agregar cache/materialized views por tenant-periodo si el dashboard supera el tiempo objetivo.
