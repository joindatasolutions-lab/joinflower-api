# Modulos - Guia Tecnica Backend

Documento tecnico orientado a backend/API para referencia de desarrollo, soporte y QA tecnico.

## 1) Arquitectura general

- Stack: FastAPI + SQLAlchemy + MySQL.
- Autenticacion: JWT (`python-jose`) + hashing (`passlib[bcrypt]`).
- Modelo de seguridad: multi-tenant por `empresaID`, rol, permisos por modulo y gating por plan.
- Patron de modulos: `routers/` (API), `services/` (reglas), `models/` (persistencia), `schemas/` (contratos).

## 2) Seguridad y contexto auth

Archivo principal: `app/core/security.py`

### Responsabilidades
- Crear/validar JWT con claims de tenant y rol.
- Resolver `AuthContext` desde token (`get_current_auth_context`).
- Validar alcance tenant (`assert_same_empresa`).
- Autorizar por modulo/accion (`require_module_access`).
- Resolver niveles de admin:
  - Global JOIN (`is_super_admin_context`)
  - Empresa admin (`is_empresa_admin_context`)

### Claims de token esperados
- `userID`
- `empresaID`
- `sucursalID`
- `rolID`
- `planID`

## 3) Modulo Auth / Usuarios

Router: `app/routers/auth.py`
Schemas: `app/schemas/auth.py`

### Endpoints
- `POST /auth/login`
- `GET /auth/me`
- `GET /auth/usuarios`
- `POST /auth/usuarios`
- `PUT /auth/usuarios/{user_id}/estado`
- `GET /auth/usuarios/roles`
- `GET /auth/usuarios/sucursales`
- `GET /auth/usuarios/empresas`

### Reglas tecnicas clave
- Login por `login` unico (no por empresa+email en UI).
- `empresa-admin` no puede operar sobre otra empresa.
- Bloqueo de creacion de roles estructurales por `empresa-admin`.
- Limite de usuarios por plan (`PLAN_USER_LIMITS_JSON` + fallback).
- Auditoria de acciones en `UsuarioAuditoria`.

### Tablas relacionadas
- `Usuario`, `Rol`, `PermisoModulo`, `PlanModulo`, `UsuarioAuditoria`.

## 4) Modulo Pedidos

Router: `app/routers/pedido.py`
Service: `app/services/pedido_service.py`
Schemas: `app/schemas/pedido.py`

### Endpoints
- `GET /pedidos`
- `GET /pedido/{pedido_id}/detalle`
- `GET /pedido/{pedido_id}/factura`
- `PUT /pedido/{pedido_id}/aprobar`
- `PUT /pedido/{pedido_id}/rechazar`
- `POST /pedido/checkout`
- `POST /pedido`
- `PUT /pedido/{pedido_id}/estado/{nuevo_estado_id}`

### Reglas tecnicas clave
- Todas las operaciones validan tenant via `assert_same_empresa`.
- Factura solo en estados permitidos (aprobado/pagado, segun regla vigente).
- Al aprobar/cambiar a aprobado-pagado dispara aseguramiento de produccion.
- Checkout crea `Entrega` con campos operativos base para Domicilios.

## 5) Modulo Produccion

Router: `app/routers/produccion.py`
Service: `app/services/produccion_service.py`
Schemas: `app/schemas/produccion.py`

### Endpoints
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

### Reglas tecnicas clave
- Estrategia sin polling masivo (cloud-run friendly):
  - Autoasignacion al aprobar pedido si fecha programada es hoy.
  - Autoasignacion al abrir `GET /produccion` para pendientes de hoy sin florista.
  - Trigger manual `POST /produccion/asignar-pendientes-hoy`.
- Reasignacion auditada con motivo y usuario.
- Restricciones por capacidad diaria/simultaneidad/estado florista.
- Si domicilio asociado esta `EnRuta`, se bloquean cambios criticos de produccion.

## 6) Modulo Domicilios

Router: `app/routers/domicilios.py`
Service: `app/services/domicilio_service.py`
Schemas: `app/schemas/domicilios.py`

### Endpoints
- `GET /domicilios`
- `GET /domicilios/domiciliarios`
- `GET /domicilios/mis-entregas`
- `PUT /domicilios/{entrega_id}/asignar`
- `PUT /domicilios/{entrega_id}/en-ruta`
- `PUT /domicilios/{entrega_id}/entregado`
- `PUT /domicilios/{entrega_id}/no-entregado`

### Reglas tecnicas clave
- Maquina de estados de entrega en servicio (`TRANSICIONES_VALIDAS`).
- Evidencia obligatoria para `entregado` (firma/datos/coords).
- Soporte de reintentos y reprogramacion para `no-entregado`.
- Integracion con Produccion cuando pasa a `ParaEntrega`.

## 7) Catalogo, Clientes y Barrios

Routers:
- `app/routers/catalogo.py`
- `app/routers/cliente.py`
- `app/routers/barrios.py`

### Endpoints
- `GET /catalogo/{empresa_id}`
- `GET /cliente/buscar/{empresaID}/{identificacion}`
- `GET /barrios/search`

### Reglas tecnicas clave
- Todos protegidos por permisos de modulo + validacion tenant.

## 8) Migraciones y bootstrap tecnico

### SQL relevantes
- `sql/alter_auth_multitenant.sql`
- `sql/alter_usuario_login_unique.sql`
- `sql/alter_usuario_sucursal.sql`
- `sql/alter_usuario_auditoria.sql`
- `sql/alter_domicilios_module.sql`
- `sql/alter_produccion_cloudrun_indexes.sql`

### Script local
- `scripts/init_auth_local.py`
  - Aplica migraciones clave con tolerancia a re-ejecucion.
  - Asegura usuario admin local y datos base de auth.

## 9) Checklist tecnico de smoke test

1. `POST /auth/login` y `GET /auth/me`.
2. `GET /auth/usuarios` con superadmin y empresa-admin.
3. `PUT /pedido/{id}/aprobar` y verificar creacion/estado de produccion.
4. `GET /produccion` y revisar bloque `autoAsignacion`.
5. Flujo domicilios: asignar -> en-ruta -> entregado/no-entregado.
