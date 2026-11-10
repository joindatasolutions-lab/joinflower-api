# Ficha del cliente

Aplicar `sql/alter_cliente_ficha.sql` antes de usar perfil, notas o comunicaciones.
La migración crea tablas nuevas; no modifica los datos personales existentes.
No se ejecuta automáticamente al iniciar la API.

Todas las rutas requieren autenticación y validan que el cliente pertenezca a
`tenant_id`. Lectura requiere `pedidos.puedeVer`; PATCH y POST de esta ficha
requieren `pedidos.puedeEditar`. Un cliente o pedido ajeno devuelve 404 y un
tenant no autorizado devuelve 403. Los pedidos se validan también contra el cliente.

## Mapeo de pantalla

| Componente | Endpoint |
|---|---|
| Buscador lateral | `GET /clientes?empresaID=3&includeMetrics=true&q=Ana&page=1&pageSize=50` |
| Con compras / Sin compras | Añadir `has_purchases=true` / `false`; omitir para todos |
| Agregar cliente | `POST /clientes` (existente) |
| Editar datos personales y fechas | `PUT /clientes/{cliente_id}` (existente, enviar payload completo) |
| Cabecera, resumen, segmentos, preferencias, oportunidades | `GET /tenants/{tenant_id}/customers/{customer_id}` |
| Editar dirección y preferencias declaradas | `PATCH /tenants/{tenant_id}/customers/{customer_id}/profile` |
| Historial | `GET /tenants/{tenant_id}/customers/{customer_id}/orders` |
| Detalle de una compra | `GET /tenants/{tenant_id}/customers/{customer_id}/orders/{order_id}` |
| Consultar / agregar notas | `GET` / `POST /tenants/{tenant_id}/customers/{customer_id}/notes` |
| Consultar / registrar comunicación manual | `GET` / `POST /tenants/{tenant_id}/customers/{customer_id}/communications` |

## Resumen de ficha

```json
{
  "customer": {
    "clienteID": 125, "empresaID": 3,
    "tipoIdent": "CC", "identificacion": "1000000000",
    "indicativo": "57", "nombreCompleto": "Cliente ejemplo",
    "telefono": null, "telefonoCompleto": null, "email": null,
    "fechaCumpleanos": null, "fechaAniversario": null,
    "activo": true, "createdAt": null, "updatedAt": null
  },
  "profile": {
    "address": null,
    "preferred_channel": null,
    "preferred_occasion": null,
    "preferences": null
  },
  "metrics": {},
  "opportunities": []
}
```

`metrics` usa exactamente el objeto `customer` de la ruta existente
`GET /tenants/{tenant_id}/customers/{customer_id}/metrics`:

- Tarjetas: `purchase_count`, `total_spent`, `first_purchase_at`, `last_purchase_at`.
- Segmentos: `segments`, `commercial_priority`, `commercial_priority_label`.
- Puntuación: `intelligence.customer_health_score`.
- Riesgo y recompra: `intelligence.churn_risk_probability`, `intelligence.repurchase_probability`.
- Recomendación: `intelligence.next_best_action`.
- Preferencias inferidas: `favorite_product`, `favorite_category`, `preferred_channel`, `average_price_range`.

La estructura completa se documenta en `clientes_metricas_backend.md` y la define
`_customer_metric_item` en `app/routers/cliente.py`. Un comprador sin pedidos tiene
contadores cero y fechas nulas. `metrics` es null si el cliente está excluido por
las reglas de analítica existentes (por ejemplo nombres que contienen "prueba").
No mostrar contadores nulos como cero en ese caso.

`opportunities` usa los mismos objetos que `/customers/opportunities`, pero solo
para el cliente seleccionado y hasta 365 días: `occasion`, `date`,
`days_remaining`, identificadores, preferencias y métricas históricas. Puede
haber un cumpleaños y un aniversario. Las fechas registradas originales están
en `customer`; no dependen de la existencia de una oportunidad.

`profile` contiene preferencias declaradas. No reemplaza los cálculos históricos.
Para la vista puede usarse `profile.preferred_channel ?? metrics.preferred_channel`.
La dirección es del comprador: no se infiere de direcciones de destinatarios.

## Actualizar perfil

```http
PATCH /tenants/3/customers/125/profile
Content-Type: application/json

{"address":"Calle 10 # 20-30","preferred_channel":"WhatsApp","preferred_occasion":"Aniversario","preferences":"Prefiere rosas blancas"}
```

Devuelve `{"profile": {...}}` con los cuatro campos. Solo actualiza los campos
enviados; null elimina un valor. Rechaza propiedades desconocidas. No modifica
nombre, documento, contacto ni fechas: esos campos usan el PUT existente.

## Historial

Parámetros: `start_date`, `end_date` (YYYY-MM-DD, inclusivos), `status`,
`page` (1), `limit` (20, máximo 100). Orden: fecha descendente y luego ID descendente.
Incluye todos los estados; las métricas existentes solo cuentan APROBADO.

```json
{
  "total": 1, "page": 1, "limit": 20,
  "data": [{
    "order_id": 1524, "number": 24, "code": "FL-24",
    "ordered_at": "2026-10-19T12:00:00", "status": "APROBADO",
    "total": 185000.0, "delivery_cost": 10000.0, "counts_as_purchase": true
  }]
}
```

El detalle de pedido reutiliza `PedidoDetalleResponse` y la misma lógica de
`GET /pedido/{pedido_id}/detalle`, después de verificar empresa y comprador.
No duplica cálculos de pagos, productos o entrega.

## Notas e interacciones manuales

Crear nota (201):

```json
{"content":"Prefiere que lo contacten en la tarde."}
```

Registrar comunicación (201):

```json
{
  "content":"Se realizó llamada para confirmar preferencias.",
  "channel":"PHONE",
  "direction":"OUTBOUND",
  "occurred_at":"2026-10-19T10:30:00-05:00"
}
```

`channel`: WHATSAPP, EMAIL, PHONE, IN_PERSON u OTHER.
`direction`: INBOUND u OUTBOUND. `occurred_at` es opcional y por defecto es ahora.
Fechas con zona se normalizan a Bogotá; fechas sin zona se interpretan como Bogotá.
El autor se toma del usuario autenticado; no puede enviarse en el cuerpo.
Contenido obligatorio de 1 a 10000 caracteres, sin contar espacios exteriores.

POST devuelve el registro creado:

```json
{
  "id": 1, "content":"Se realizó llamada para confirmar preferencias.",
  "channel":"PHONE", "direction":"OUTBOUND",
  "occurred_at":"2026-10-19T10:30:00", "author_id":7,
  "created_at":"2026-10-19T10:31:00"
}
```

En las notas, channel y direction son null. Cada GET admite `page` y `limit`
(20 por defecto, máximo 100) y devuelve `{"total":0,"page":1,"limit":20,"data":[]}`
con esos registros, ordenados por ocurrido_at e ID descendentes. El total se
calcula antes de paginar. Las notas y comunicaciones tienen listas independientes.

Registrar una comunicación NO envía un mensaje, no marca entrega ni crea un
mensaje en WhatsApp o correo. El botón de la captura debe adaptarse a "Registrar
comunicación" para este alcance. No se integró un proveedor de envío.

## Validación

`python -m pytest tests/test_cliente_ficha.py tests/test_cliente_metrics.py -q`

Las pruebas locales utilizan SQLite para validar aislamiento, filtros,
paginación, clientes sin compras, notas, interacciones y actualización parcial.
La migración PostgreSQL debe aplicarse y verificarse en el entorno destino;
las pruebas locales no representan una ejecución de esa migración en producción.
