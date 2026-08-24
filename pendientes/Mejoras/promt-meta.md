Necesito implementar en el backend de **PetalOps** una funcionalidad multi-tenant para enviar una notificación por **WhatsApp Business Platform / Meta Cloud API** exclusivamente cuando un pedido sea marcado como **ENTREGADO**.

PetalOps maneja múltiples negocios o tenants, por ejemplo:

* FLORA
* Lafiore
* futuros negocios asociados

Actualmente todos los mensajes saldrán desde **un único número de WhatsApp de PetalOps/Join Data**, pero el mensaje debe identificar claramente el negocio al cual pertenece el pedido.

La prioridad máxima es evitar errores de aislamiento multi-tenant: **un cliente de FLORA nunca puede recibir información de Lafiore ni viceversa**.

# 1. Regla principal de seguridad multi-tenant

NO confiar únicamente en un `tenant_id`, `cliente_id`, teléfono, nombre de negocio o cualquier otro dato enviado desde el frontend.

Cuando se solicite enviar una notificación:

1. recibir únicamente el identificador interno del pedido o procesar el evento generado por el backend;
2. consultar el pedido directamente en la base de datos;
3. obtener desde la relación del pedido:

   * `tenant_id`;
   * `cliente_id`;
   * estado;
   * número del pedido;
4. obtener el tenant desde `tenant_id`;
5. obtener el cliente únicamente dentro de ese mismo tenant;
6. obtener el teléfono asociado a ese cliente;
7. validar nuevamente que:

```text
pedido.tenant_id == cliente.tenant_id
pedido.tenant_id == tenant.id
```

Si cualquiera de estas validaciones falla:

* NO enviar WhatsApp;
* registrar un error de seguridad;
* abortar el procesamiento.

Nunca realizar una consulta de cliente solamente por `cliente_id` sin validar también el `tenant_id`.

Preferir consultas equivalentes a:

```sql
WHERE cliente.id = :cliente_id
AND cliente.tenant_id = :tenant_id
```

# 2. No aceptar teléfono desde el frontend

El endpoint de notificación NO debe aceptar algo como:

```json
{
  "pedido_id": 123,
  "telefono": "573001234567",
  "tenant": "flora"
}
```

Eso permitiría enviar mensajes al número incorrecto.

Preferir:

```json
{
  "pedido_id": 123
}
```

y que el backend resuelva toda la información.

Idealmente ni siquiera debe depender de un endpoint manual: el envío debe dispararse desde un evento interno cuando el estado del pedido pase correctamente a `ENTREGADO`.

# 3. Evento que dispara la notificación

La notificación solamente se debe ejecutar cuando exista una transición válida hacia:

```text
ENTREGADO
```

Ejemplo:

```text
PARA_ENTREGAR
      ↓
ENTREGADO
      ↓
ORDER_DELIVERED
      ↓
WhatsAppNotificationService
```

No enviar el mensaje simplemente porque alguien haga una llamada repetida al endpoint.

# 4. Idempotencia obligatoria

Un mismo pedido no puede generar múltiples WhatsApp de entrega.

Crear una protección de idempotencia utilizando una clave equivalente a:

```text
tenant_id + pedido_id + ORDER_DELIVERED
```

Ejemplo:

```text
flora:1234:ORDER_DELIVERED
```

Antes de enviar consultar si existe una notificación exitosa para esa combinación.

Si existe:

```text
NO volver a enviar.
```

Implementar además una restricción UNIQUE en base de datos equivalente a:

```text
UNIQUE (
    tenant_id,
    pedido_id,
    evento,
    canal
)
```

Esto debe proteger incluso frente a:

* doble clic;
* retries HTTP;
* concurrencia;
* múltiples workers;
* reintentos automáticos;
* llamadas repetidas.

# 5. Tabla de notificaciones

Crear o utilizar una tabla equivalente a:

```text
notifications
-------------
id
tenant_id
pedido_id
cliente_id
canal
evento
telefono_destino
template_name
meta_message_id
status
attempts
created_at
sent_at
delivered_at
read_at
failed_at
error_code
error_message
```

Valores:

```text
canal = WHATSAPP
evento = ORDER_DELIVERED
```

Estados internos posibles:

```text
PENDING
SENT
DELIVERED
READ
FAILED
SKIPPED
```

# 6. Número de teléfono

Crear una función única para normalizar teléfonos.

Para Colombia, por ejemplo:

```text
3001234567
```

debe convertirse internamente a:

```text
573001234567
```

antes de enviarlo a Meta.

Validar:

* que exista teléfono;
* formato válido;
* código de país;
* longitud razonable.

Nunca intentar enviar si el teléfono es nulo, vacío o inválido.

Registrar:

```text
SKIPPED_INVALID_PHONE
```

sin generar excepción que afecte el flujo principal del pedido.

# 7. Mensaje

Utilizar una plantilla aprobada por Meta clasificada como:

```text
UTILITY
```

Nombre sugerido:

```text
pedido_entregado
```

No construir mensajes libres cuando se trate de notificaciones iniciadas por PetalOps fuera de la ventana permitida por WhatsApp.

El mensaje debe incluir obligatoriamente el nombre real del tenant.

Ejemplo conceptual:

```text
FLORA

Hola María,

tu pedido #1234 ha sido entregado correctamente.

Gracias por confiar en FLORA.
```

Para Lafiore:

```text
Lafiore

Hola Carlos,

tu pedido #829 ha sido entregado correctamente.

Gracias por confiar en Lafiore.
```

Las variables deben provenir exclusivamente de la base de datos.

Ejemplo:

```text
{{1}} = tenant.nombre
{{2}} = cliente.nombre
{{3}} = pedido.numero
```

No hardcodear:

```python
if tenant == "flora":
...
elif tenant == "lafiore":
...
```

La misma implementación debe funcionar automáticamente para cualquier nuevo tenant.

# 8. Protección frente a envíos incorrectos

Antes de llamar a Meta realizar una validación final:

```python
assert pedido.tenant_id == tenant.id
assert cliente.tenant_id == tenant.id
assert pedido.cliente_id == cliente.id
assert pedido.estado == "ENTREGADO"
```

No utilizar `assert` como único mecanismo de producción; implementar validaciones explícitas y errores controlados.

Si existe inconsistencia:

```text
SECURITY_TENANT_MISMATCH
```

Registrar el incidente y NO enviar.

# 9. Protecciones de reputación de WhatsApp

No implementar mecanismos destinados a evadir controles o límites de Meta.

Implementar prácticas de uso seguro:

* únicamente mensajes transaccionales relacionados con pedidos reales;
* utilizar plantillas aprobadas;
* no enviar publicidad en esta funcionalidad;
* no realizar envíos masivos;
* no recorrer automáticamente todos los clientes;
* no enviar a contactos sin relación con un pedido;
* no enviar repetidamente el mismo mensaje;
* respetar bajas u opt-out cuando corresponda;
* mantener registro de la procedencia del teléfono;
* aplicar rate limiting;
* implementar retries controlados únicamente para errores transitorios.

# 10. Rate limiting

Crear protección para evitar picos accidentales.

No insertar `sleep()` bloqueantes dentro de requests HTTP.

Diseñar el servicio para poder utilizar una cola/job asíncrono.

La primera versión puede procesarse de manera simple, pero separar:

```text
cambio de estado
        ↓
crear evento/notificación
        ↓
worker / servicio de notificaciones
        ↓
Meta Cloud API
```

El cambio del pedido a ENTREGADO no debe depender de que Meta responda correctamente.

Si WhatsApp falla:

```text
pedido = ENTREGADO
notification = FAILED
```

Nunca hacer rollback del estado operativo del pedido porque WhatsApp falló.

# 11. Retries

Realizar retries únicamente ante errores transitorios como:

```text
429
5xx
timeout
connection error
```

Utilizar exponential backoff.

Ejemplo:

```text
intento 1
↓
30 segundos
↓
intento 2
↓
2 minutos
↓
intento 3
```

Definir un máximo de intentos.

NO hacer retry automático ante errores permanentes como:

* teléfono inválido;
* template inexistente;
* destinatario inválido;
* autorización inválida;
* configuración incorrecta.

# 12. Credenciales

Nunca guardar:

```text
META_ACCESS_TOKEN
META_APP_SECRET
PHONE_NUMBER_ID
```

hardcodeados en código, Git o base de datos en texto plano.

Utilizar variables de entorno / Secret Manager.

Ejemplo:

```text
META_WHATSAPP_ACCESS_TOKEN
META_WHATSAPP_PHONE_NUMBER_ID
META_WHATSAPP_API_VERSION
```

# 13. Arquitectura

Crear un servicio desacoplado equivalente a:

```text
services/
    whatsapp/
        client.py
        service.py
        schemas.py
        exceptions.py
```

Responsabilidades:

```text
WhatsAppClient
    ↓
solamente comunicación HTTP con Meta

WhatsAppNotificationService
    ↓
reglas de negocio
tenant
pedido
cliente
idempotencia
templates
logs
```

No colocar toda la lógica dentro del endpoint que actualiza el pedido.

# 14. Flujo esperado

Implementar este flujo:

```text
Pedido 1234
tenant_id = FLORA

        ↓

estado cambia a ENTREGADO

        ↓

Backend consulta pedido

        ↓

obtiene tenant FLORA

        ↓

obtiene cliente perteneciente a FLORA

        ↓

obtiene teléfono del cliente

        ↓

valida tenant/pedido/cliente

        ↓

consulta idempotencia

        ↓

crea notification PENDING

        ↓

envía template UTILITY mediante Meta

        ↓

guarda wamid

        ↓

notification = SENT
```

Para Lafiore:

```text
Pedido 888
tenant_id = LAFIORE
```

debe recorrer exactamente el mismo código, cambiando únicamente los datos obtenidos desde base de datos.

# 15. Caso crítico que debe impedirse

Este escenario debe ser imposible:

```text
Pedido FLORA
+
cliente Lafiore
+
teléfono cliente Lafiore
```

Aunque alguien manipule parámetros desde frontend o API.

Agregar tests automatizados explícitos para demostrarlo.

# 16. Pruebas obligatorias

Crear pruebas unitarias/integración para:

### Caso 1

Pedido FLORA + cliente FLORA:

```text
envía correctamente
```

### Caso 2

Pedido Lafiore + cliente Lafiore:

```text
envía correctamente
```

### Caso 3

Pedido FLORA + cliente Lafiore:

```text
NO envía
SECURITY_TENANT_MISMATCH
```

### Caso 4

Pedido entregado dos veces:

```text
solo un WhatsApp
```

### Caso 5

Teléfono inválido:

```text
NO envía
SKIPPED
```

### Caso 6

Meta devuelve 500:

```text
pedido permanece ENTREGADO
notificación pasa a retry/FAILED
```

### Caso 7

Dos workers procesan simultáneamente el mismo pedido:

```text
solo uno puede enviar
```

### Caso 8

Se intenta enviar un pedido que no está ENTREGADO:

```text
NO enviar
```

# 17. Logging

Registrar información suficiente para auditoría, pero no imprimir access tokens ni secretos.

Ejemplo:

```text
event=ORDER_DELIVERED
tenant_id=...
pedido_id=...
cliente_id=...
notification_id=...
meta_message_id=...
status=SENT
```

Enmascarar el teléfono en logs:

```text
******4567
```

# 18. No implementar todavía

Por ahora NO implementar:

* chatbot;
* respuestas automáticas;
* agente IA;
* promociones;
* campañas;
* recuperación de clientes;
* recomendaciones;
* mensajes de carrito abandonado;
* mensajes masivos;
* demás estados del pedido.

La única funcionalidad de esta iteración es:

```text
PEDIDO ENTREGADO
        ↓
NOTIFICACIÓN WHATSAPP
```

# 19. Antes de modificar

Primero analiza el código actual de PetalOps e identifica:

* modelo de tenants;
* modelo de pedidos;
* modelo de clientes;
* relación pedido → tenant;
* relación cliente → tenant;
* lógica actual de cambio a ENTREGADO;
* mecanismo de sesiones/transacciones;
* arquitectura actual de servicios;
* posibles sistemas de colas existentes.

No asumir nombres de tablas, campos o endpoints.

Reutilizar la arquitectura existente siempre que sea razonable.

Antes de escribir código, mostrar:

1. archivos que serán modificados;
2. archivos nuevos;
3. modelo de datos propuesto;
4. flujo de ejecución;
5. mecanismo exacto para garantizar aislamiento entre tenants;
6. mecanismo de idempotencia;
7. riesgos encontrados.

Después implementar.
