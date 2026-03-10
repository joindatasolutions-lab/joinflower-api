# Modulos: funcionalidades y uso

Este documento resume que hace cada modulo del sistema y como usarlo en operacion.

## 1) Autenticacion y Gestion de Usuarios

### Que resuelve
- Login con usuario unico (`login`) y contrasena.
- Contexto multi-tenant en JWT (`empresaID`, `sucursalID`, `rolID`, `planID`).
- Control de acceso por rol, permisos por modulo y restricciones por plan.
- Administracion de usuarios (crear, listar, activar/inactivar) con alcance por nivel:
  - SuperAdmin global JOIN.
  - Admin de empresa.

### Endpoints clave
- `POST /auth/login`
- `GET /auth/me`
- `GET /auth/usuarios`
- `POST /auth/usuarios`
- `PUT /auth/usuarios/{user_id}/estado`
- `GET /auth/usuarios/roles`
- `GET /auth/usuarios/sucursales`
- `GET /auth/usuarios/empresas` (solo global JOIN)

### Como se usa
1. Iniciar sesion con `login` y `password`.
2. Guardar `accessToken` en frontend.
3. Consumir `GET /auth/me` para construir menu, permisos y vistas.
4. En Gestion de Usuarios:
   - SuperAdmin puede trabajar cross-tenant.
   - Admin empresa queda limitado a su empresa.

### Notas operativas
- Empresa-admin no debe crear roles estructurales.
- Si no hay roles operativos disponibles, la creacion de usuarios debe bloquearse.

## 2) Pedidos

### Que resuelve
- Consulta operativa de pedidos con filtros.
- Aprobacion/rechazo con reglas de estado.
- Descarga de factura para estados permitidos.
- Checkout transaccional del pedido.

### Endpoints clave
- `GET /pedidos`
- `GET /pedido/{pedido_id}/detalle`
- `GET /pedido/{pedido_id}/factura`
- `PUT /pedido/{pedido_id}/aprobar`
- `PUT /pedido/{pedido_id}/rechazar`
- `POST /pedido/checkout`
- `POST /pedido`
- `PUT /pedido/{pedido_id}/estado/{nuevo_estado_id}`

### Como se usa
1. Buscar pedidos por `empresaID` y opcionalmente `sucursalID`, fechas, estado y texto.
2. Abrir detalle para validar cliente, destinatario, productos y total.
3. Aprobar o rechazar segun reglas de negocio.
4. Descargar factura cuando el pedido este en estado permitido.

### Integracion con Produccion
- Al aprobar/pagar pedido se asegura registro en Produccion.
- Si la fecha programada cae hoy, puede autoasignarse florista.

## 3) Produccion

### Que resuelve
- Planeacion y ejecucion de produccion por pedido.
- Asignacion manual o automatica de floristas.
- Reasignacion auditada con historial.
- Control de estados (`Pendiente`, `EnProduccion`, `ParaEntrega`, `Cancelado`).
- Metricas e historial de productividad/operacion.

### Endpoints clave
- `POST /produccion/generar-desde-pedidos`
- `GET /produccion`
- `POST /produccion/asignar-pendientes-hoy`
- `GET /produccion/floristas`
- `PUT /produccion/floristas/{florista_id}/estado`
- `POST /produccion/floristas/sincronizar-incapacidades`
- `PUT /produccion/{produccion_id}/asignar`
- `PUT /produccion/{produccion_id}/reasignar`
- `PUT /produccion/{produccion_id}/estado`
- `POST /produccion/pedido/{pedido_id}/recalcular`
- `GET /produccion/historial/reasignaciones`
- `GET /produccion/metricas/productividad`
- `GET /produccion/metricas/operacion`

### Como se usa
1. Abrir modulo con `GET /produccion` (puede disparar autoasignacion de pendientes de hoy).
2. Asignar o reasignar florista si hace falta.
3. Cambiar estado segun flujo operativo.
4. Consultar historial y metricas para seguimiento.

### Reglas clave
- Sin polling masivo: asignacion por evento y por apertura de modulo.
- No asignar manualmente producciones de fecha futura.
- Si domicilio esta `EnRuta`, se bloquean cambios en produccion.

## 4) Domicilios

### Que resuelve
- Gestion de ultima milla desde `ParaEntrega` hasta `Entregado` o `NoEntregado`.
- Asignacion de domiciliario.
- Evidencia de entrega (firma, documento, foto opcional, geolocalizacion).
- Manejo de no entrega y reprogramacion.

### Endpoints clave
- `GET /domicilios`
- `GET /domicilios/domiciliarios`
- `GET /domicilios/mis-entregas`
- `PUT /domicilios/{entrega_id}/asignar`
- `PUT /domicilios/{entrega_id}/en-ruta`
- `PUT /domicilios/{entrega_id}/entregado`
- `PUT /domicilios/{entrega_id}/no-entregado`

### Como se usa
1. Vista admin: filtrar por fecha/estado y asignar domiciliarios.
2. Vista domiciliario: tomar entregas asignadas y ejecutar estados.
3. En entrega exitosa: registrar evidencia obligatoria.
4. Si no se entrega: registrar motivo y reprogramacion opcional.

### Reglas de estado
- `Pendiente -> Asignado -> EnRuta -> Entregado`
- `EnRuta -> NoEntregado` con motivo.

## 5) Catalogo

### Que resuelve
- Consulta de productos disponibles por empresa para armado de pedido.

### Endpoint clave
- `GET /catalogo/{empresa_id}`

### Como se usa
1. Cargar catalogo al iniciar flujo de venta.
2. Mostrar producto, categoria y precio al usuario final/admin.

## 6) Clientes

### Que resuelve
- Busqueda de cliente por identificacion dentro de empresa.

### Endpoint clave
- `GET /cliente/buscar/{empresaID}/{identificacion}`

### Como se usa
1. Buscar cliente antes de crear pedido.
2. Reusar datos existentes para reducir errores de captura.

## 7) Barrios

### Que resuelve
- Autocompletado de barrios para direccion de entrega.

### Endpoint clave
- `GET /barrios/search?q=...&empresa_id=...&sucursal_id=...`

### Como se usa
1. Capturar al menos 2 caracteres en el campo barrio.
2. Seleccionar sugerencia para estandarizar direccion.

## 8) Flujo recomendado de punta a punta

1. Usuario inicia sesion (`/auth/login`) y carga perfil (`/auth/me`).
2. Se crea pedido (`/pedido/checkout` o flujo admin) y queda en estado inicial.
3. Pedido se aprueba (`/pedido/{id}/aprobar`).
4. Produccion genera/asigna tarea y avanza estado hasta `ParaEntrega`.
5. Domicilios toma la entrega, pasa a `EnRuta` y luego `Entregado` o `NoEntregado`.
6. Gestion de usuarios administra acceso y operacion segun rol y alcance.

## 9) Recomendaciones de uso en frontend

- Construir UI desde `GET /auth/me` (no hardcodear permisos).
- Ocultar acciones no permitidas por rol/plan.
- Mostrar mensajes de error claros para `403` (sin permisos) y `400` (regla de negocio).
- En Gestion de Usuarios, diferenciar visualmente panel global vs panel empresa.
