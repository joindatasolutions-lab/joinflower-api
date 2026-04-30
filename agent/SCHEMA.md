# Petalops — Diccionario de datos para agente de código

## Contexto del sistema

Plataforma multitenant SaaS para gestión de floristerías. Cada floristería es una `empresa`
que puede tener una o más `sucursal`. Cada sucursal tiene su propio catálogo web, flujo de
pedidos, producción y domicilios. Todo dato está aislado por `empresa_id` — nunca se deben
mezclar datos entre empresas en ninguna query.

Schema PostgreSQL: `petalops`

---

## Arquitectura general

```
platform (superadmin)
  └── empresa (floristería)
        └── sucursal (1..N)
              ├── producto_sucursal   → catálogo web con precios por sucursal
              ├── barrio              → zonas de domicilio con costo
              ├── inventario          → stock de insumos por sucursal
              └── empleado            → personal (floristas, domiciliarios, cajeros)

pedido (cliente hace pedido en sucursal)
  ├── pedido_detalle (productos del pedido)
  ├── pago (pasarela o manual)
  ├── produccion (un registro por detalle, asignado a florista)
  └── entrega (uno o más intentos de domicilio)
```

---

## Superadmin de plataforma

El superadmin vive en `petalops.usuario` con `es_superadmin = true` y `empresa_id = NULL`.

Un check constraint en BD garantiza la exclusión mutua:
- `es_superadmin = true`  → `empresa_id`, `sucursal_id` y `rolid` deben ser NULL
- `es_superadmin = false` → `empresa_id`, `sucursal_id` y `rolid` deben ser NOT NULL

**Acciones exclusivas del superadmin:**
- Crear / editar / desactivar empresas
- Asignar y cambiar planes
- Crear el usuario admin inicial de una empresa nueva
- Ver métricas globales (queries sin filtro de empresa_id)
- Impersonar empresa para soporte técnico

**Regla crítica:** Nunca filtrar por `empresa_id` cuando `es_superadmin = true`.
Usar siempre el helper `tenantFilter(user)` antes de construir cualquier query.
El superadmin nunca debe aparecer en listados de usuarios de empresa —
agregar `AND es_superadmin = false` en toda query que liste usuarios de una empresa.

---

## Tablas

---

### empresa
Entidad raíz del sistema. Representa una floristería cliente de la plataforma.

| columna | tipo | null | descripción |
|---|---|---|---|
| id_empresa | integer | NO | PK, autoincremental |
| nombre_empresa | varchar(150) | NO | Nombre legal. UNIQUE |
| nit | varchar(30) | NO | NIT o RUT. UNIQUE |
| estado | integer | NO | 1=activa, 0=inactiva |
| dominio | varchar(120) | SÍ | Dominio web personalizado. índice |
| slug | varchar(50) | SÍ | Identificador URL. UNIQUE |
| logo_url | varchar(500) | SÍ | URL del logo en S3 |
| nombre_comercial | varchar(180) | SÍ | Nombre visible en catálogo |
| plan_id | bigint | SÍ | FK → plan. Plan contratado |
| created_at | timestamp | NO | |
| updated_at | timestamp | NO | |

**Reglas:** Toda tabla del sistema tiene `empresa_id` FK hacia esta tabla. Nunca hacer queries cross-empresa.

---

### sucursal
Punto físico de operación de una empresa. Una empresa puede tener N sucursales.

| columna | tipo | null | descripción |
|---|---|---|---|
| id_sucursal | integer | NO | PK |
| empresa_id | bigint | NO | FK → empresa. UNIQUE con nombre_sucursal |
| nombre_sucursal | varchar(120) | NO | UNIQUE por empresa |
| direccion | varchar(200) | SÍ | |
| telefono | varchar(30) | SÍ | |
| estado | varchar(30) | NO | 'activa' / 'inactiva' |
| prefijo_pedido | varchar(12) | SÍ | Prefijo para número de pedido (ej: 'BOG') |
| created_at | timestamp | NO | |
| updated_at | timestamp | SÍ | |

---

### plan
Planes de suscripción disponibles en la plataforma.

| columna | tipo | null | descripción |
|---|---|---|---|
| id_plan | bigint | NO | PK |
| nombre | varchar(100) | NO | |
| descripcion | varchar(255) | SÍ | |
| empresa_id | bigint | SÍ | FK → empresa. NULL = plan global de plataforma |

---

### plan_modulo
Módulos habilitados por plan. PK compuesta (plan_id, modulo).

| columna | tipo | null | descripción |
|---|---|---|---|
| plan_id | bigint | NO | PK. FK → plan. UNIQUE con modulo |
| modulo | varchar(80) | NO | PK. Código del módulo |
| activo | boolean | NO | |

---

### modulo
Catálogo master de módulos del sistema.

| columna | tipo | null | descripción |
|---|---|---|---|
| id_modulo | integer | NO | PK |
| codigo | varchar(50) | NO | UNIQUE. Ej: 'pedidos', 'produccion', 'domicilios' |
| nombre | varchar(100) | SÍ | |
| descripcion | text | SÍ | |

---

### empresa_modulo
Módulos activos por empresa (override del plan). PK compuesta (empresa_id, modulo).

| columna | tipo | null | descripción |
|---|---|---|---|
| empresa_id | bigint | NO | PK. FK → empresa |
| modulo | varchar(80) | NO | PK. Código del módulo |
| activo | integer | NO | 1=activo, 0=inactivo |
| updatedat | timestamp | NO | |

**Regla de autorización:** La jerarquía es `plan_modulo` → `empresa_modulo` → `permiso_modulo(rol)` → `usuario_modulo`.
Un módulo debe estar activo en todos los niveles para que el usuario tenga acceso.

---

### rol
Roles de acceso al sistema, definidos por empresa.

| columna | tipo | null | descripción |
|---|---|---|---|
| id_rol | integer | NO | PK |
| empresa_id | bigint | NO | FK → empresa. UNIQUE con nombre_rol |
| nombre_rol | varchar(80) | NO | Ej: 'Admin', 'Florista', 'Domiciliario'. UNIQUE por empresa |

---

### permiso_modulo
Permisos CRUD por rol y módulo. PK compuesta (rol_id, modulo).

| columna | tipo | null | descripción |
|---|---|---|---|
| rol_id | bigint | NO | PK. FK → rol ON DELETE CASCADE. UNIQUE con modulo |
| modulo | varchar(80) | NO | PK. Código del módulo |
| empresa_id | integer | NO | Desnormalizado para queries rápidas |
| puede_ver | boolean | NO | |
| puede_crear | boolean | NO | |
| puede_editar | boolean | NO | |
| puede_eliminar | boolean | NO | |

---

### usuario
Usuarios con acceso al sistema. Incluye usuarios de empresa y el superadmin de plataforma.

| columna | tipo | null | descripción |
|---|---|---|---|
| id_usuario | integer | NO | PK |
| empresa_id | bigint | **SÍ** | FK → empresa. NULL si es_superadmin=true |
| nombre | varchar(150) | NO | |
| email | varchar(180) | NO | UNIQUE por empresa |
| login | varchar(80) | NO | UNIQUE global |
| passwordhash | varchar(255) | NO | Bcrypt |
| rolid | bigint | **SÍ** | FK → rol. NULL si es_superadmin=true |
| sucursal_id | bigint | **SÍ** | Sucursal asignada. NULL si es_superadmin=true |
| estado | varchar(20) | NO | 'activo' / 'inactivo' / 'bloqueado' |
| es_superadmin | boolean | NO | DEFAULT false. true = superadmin de plataforma |
| ultimo_login | timestamp | SÍ | |
| created_at | timestamp | SÍ | |
| updated_at | timestamp | SÍ | |

**Check constraints:**
- `chk_usuario_empresa_o_superadmin`: `(es_superadmin=true AND empresa_id IS NULL AND sucursal_id IS NULL) OR (es_superadmin=false AND empresa_id IS NOT NULL AND sucursal_id IS NOT NULL)`
- `chk_usuario_rol_superadmin`: `(es_superadmin=true AND rolid IS NULL) OR (es_superadmin=false AND rolid IS NOT NULL)`

---

### usuario_modulo
Overrides de módulos a nivel de usuario individual. PK compuesta (usuario_id, modulo).

| columna | tipo | null | descripción |
|---|---|---|---|
| usuario_id | bigint | NO | PK. FK → usuario |
| modulo | varchar(80) | NO | PK. Código del módulo |
| activo | boolean | NO | |
| updated_at | timestamp | NO | |

---

### usuario_auditoria
Log de acciones administrativas sobre usuarios.

| columna | tipo | null | descripción |
|---|---|---|---|
| id_audit | integer | NO | PK |
| empresa_id | bigint | NO | |
| actor_user_id | bigint | NO | Usuario que realizó la acción |
| actor_login | varchar(80) | NO | Login denormalizado para histórico |
| accion | varchar(60) | NO | Ej: 'CREAR', 'BLOQUEAR', 'CAMBIAR_ROL' |
| target_user_id | bigint | NO | Usuario afectado |
| target_login | varchar(80) | NO | |
| detalle_json | text | SÍ | JSON con detalles adicionales |
| created_at | timestamp | NO | |

---

### empleado
Personal de la empresa. Todo empleado tiene un usuario en el sistema (`usuario_id`).

| columna | tipo | null | descripción |
|---|---|---|---|
| id_empleado | integer | NO | PK |
| empresa_id | bigint | NO | FK → empresa |
| sucursal_id | bigint | SÍ | FK → sucursal |
| nombre_empleado | varchar(150) | NO | |
| cargo | varchar(100) | NO | Cargo laboral: 'Florista', 'Domiciliario', 'Cajero', etc. |
| activo | integer | NO | 1=activo, 0=inactivo |
| usuario_id | bigint | SÍ | FK → usuario. Acceso al sistema |
| usuario | varchar(120) | SÍ | **Legacy** — usar usuario_id |
| email | varchar(255) | SÍ | Email laboral |
| password_hash | varchar(255) | SÍ | **Legacy** — autenticación debe ir por tabla usuario |
| identificacion | varchar(50) | SÍ | Documento de identidad. UNIQUE por empresa |
| last_login | timestamp | SÍ | **Legacy** — usar usuario.ultimo_login |
| created_at | timestamp | NO | |
| updated_at | timestamp | SÍ | |

**Nota:** Los campos `usuario`, `email`, `password_hash` y `last_login` son legacy.
La autenticación oficial vive en la tabla `usuario`. Para saber si un empleado es florista,
verificar existencia en `perfil_florista`.

---

### perfil_florista
Extensión de empleado para quienes son floristas. Relación 1-a-1 opcional con empleado.

| columna | tipo | null | descripción |
|---|---|---|---|
| empleado_id | bigint | NO | PK. FK → empleado |
| capacidad_diaria | bigint | NO | Número máximo de arreglos por día |
| trab_simul_permi | integer | NO | Trabajos simultáneos permitidos |
| especialidades | text | SÍ | Tipos de arreglos que domina |
| fecha_ini_incap | timestamp | SÍ | Inicio de incapacidad |
| fecha_fin_incap | timestamp | SÍ | Fin de incapacidad |

**Uso:** `SELECT * FROM empleado e JOIN perfil_florista pf ON pf.empleado_id = e.id_empleado`
para obtener floristas disponibles.

---

### cliente
Clientes que realizan pedidos. Aislados por empresa.

| columna | tipo | null | descripción |
|---|---|---|---|
| cliente_id | integer | NO | PK |
| empresa_id | bigint | NO | FK → empresa. UNIQUE con identificacion |
| nombre_completo | varchar(200) | NO | |
| identificacion | varchar(50) | NO | UNIQUE por empresa |
| tipo_ident | varchar(30) | SÍ | 'CC', 'NIT', 'CE', etc. |
| indicativo | varchar(10) | SÍ | Código de país para teléfono |
| telefono | varchar(30) | SÍ | |
| telefono_completo | varchar(40) | SÍ | indicativo + telefono concatenados |
| email | varchar(150) | SÍ | |
| activo | integer | NO | |
| created_at | timestamp | NO | |
| updated_at | timestamp | SÍ | |

---

### categoria
Categorías de productos, definidas por empresa.

| columna | tipo | null | descripción |
|---|---|---|---|
| id_categoria | bigint | NO | PK |
| empresa_id | bigint | NO | FK → empresa. UNIQUE con nombre normalizado |
| nombre | varchar(120) | NO | |
| created_at | timestamptz | NO | DEFAULT now() |

---

### producto
Catálogo master de productos (arreglos florales). Definido a nivel empresa.

| columna | tipo | null | descripción |
|---|---|---|---|
| id_producto | integer | NO | PK |
| empresa_id | bigint | NO | FK → empresa. UNIQUE con codigo_producto |
| categoria_id | bigint | NO | FK → categoria |
| codigo_producto | varchar(50) | NO | UNIQUE por empresa |
| nombre_producto | varchar(150) | NO | |
| descripcion | text | SÍ | |
| porcentaje_iva | numeric(5,2) | SÍ | |
| iva_incluido | boolean | SÍ | DEFAULT false |
| tiempo_base_min | integer | SÍ | Minutos estimados de producción |
| nivel_complejidad | varchar(50) | SÍ | 'bajo', 'medio', 'alto' |
| activo | boolean | NO | DEFAULT true |
| created_at | timestamp | NO | DEFAULT CURRENT_TIMESTAMP |
| updated_at | timestamp | SÍ | |

---

### producto_sucursal
Precio y disponibilidad de un producto en una sucursal. UNIQUE por (producto_id, sucursal_id).

| columna | tipo | null | descripción |
|---|---|---|---|
| id_producto_sucursal | integer | NO | PK |
| producto_id | integer | NO | FK → producto. UNIQUE con sucursal_id |
| sucursal_id | bigint | NO | FK → sucursal. UNIQUE con producto_id |
| precio | numeric(10,2) | NO | Precio de venta en esta sucursal |
| activo | boolean | NO | DEFAULT true. Controla visibilidad en catálogo |
| es_destacado | boolean | SÍ | DEFAULT false. Aparece primero en catálogo |
| orden_catalogo | integer | SÍ | Orden de aparición |
| imagen_url | varchar(500) | SÍ | URL pública de imagen |
| imagen_s3_key | varchar(255) | SÍ | Key en S3 para gestión interna |
| created_at | timestamp | NO | DEFAULT CURRENT_TIMESTAMP |
| updated_at | timestamp | SÍ | |

**Regla catálogo:**
`WHERE sucursal_id = ? AND activo = true ORDER BY es_destacado DESC, orden_catalogo ASC NULLS LAST`

---

### barrio
Zonas de domicilio con costo, definidas por empresa/sucursal.

| columna | tipo | null | descripción |
|---|---|---|---|
| id_barrio | integer | NO | PK |
| empresa_id | bigint | NO | FK → empresa. UNIQUE con sucursal_id+nombre_barrio |
| sucursal_id | bigint | SÍ | FK → sucursal. NULL = aplica a toda la empresa |
| zona_id | bigint | NO | Agrupación de barrios (sin FK declarada aún) |
| nombre_barrio | varchar(150) | NO | UNIQUE por empresa+sucursal |
| costo_domicilio | numeric(12,2) | NO | Costo de envío a este barrio |
| activo | integer | NO | |
| created_at | timestamp | NO | |
| updated_at | timestamp | SÍ | |

---

### estado_pedido
Catálogo de estados del ciclo de vida de un pedido.

| columna | tipo | null | descripción |
|---|---|---|---|
| id_estado_pedido | integer | NO | PK |
| nombre_estado | varchar(100) | NO | Ej: 'Pendiente', 'Aprobado', 'Rechazado', 'En producción' |
| descripcion | varchar(250) | SÍ | |
| orden | integer | SÍ | Orden visual en el flujo |
| activo | integer | SÍ | |
| created_at | timestamp | SÍ | |
| updated_at | timestamp | SÍ | |

---

### transicion_estado_pedido
Define qué transiciones de estado son válidas por empresa.

| columna | tipo | null | descripción |
|---|---|---|---|
| id_trans_estado_ped | integer | NO | PK |
| empresa_id | bigint | NO | FK → empresa. UNIQUE con estado_origen_id+estado_destino_id |
| estado_origen_id | bigint | NO | Estado desde el que se puede transicionar |
| estado_destino_id | bigint | NO | Estado al que se puede llegar |
| created_at | timestamp | NO | |

**Uso:** `WHERE empresa_id = ? AND estado_origen_id = ? AND estado_destino_id = ?`

---

### pedido
Pedido realizado por un cliente. Núcleo del sistema.

| columna | tipo | null | descripción |
|---|---|---|---|
| id_pedido | integer | NO | PK |
| empresa_id | bigint | NO | FK → empresa. UNIQUE con sucursal_id+numero_pedido |
| sucursal_id | bigint | NO | FK → sucursal. UNIQUE con empresa_id+numero_pedido |
| cliente_id | bigint | NO | FK → cliente |
| numero_pedido | bigint | NO | Número secuencial por sucursal. UNIQUE con empresa+sucursal |
| codigo_pedido | varchar(40) | SÍ | Código legible: prefijo + numero (ej: 'BOG-00123') |
| fecha_pedido | timestamp | NO | Fecha y hora del pedido |
| estado_pedido_id | bigint | NO | FK → estado_pedido |
| version | integer | NO | Control de concurrencia optimista |
| motivo_rechazo | varchar(300) | SÍ | Se llena cuando estado = Rechazado |
| total_bruto | numeric(12,2) | NO | Suma de subtotales sin IVA |
| total_iva | numeric(12,2) | NO | |
| total_neto | numeric(12,2) | NO | total_bruto + total_iva |
| created_at | timestamp | NO | |
| updated_at | timestamp | SÍ | |

**Flujo:** Cliente crea pedido → Pendiente → empleado aprueba/rechaza →
si aprobado, se crea `produccion` por cada `pedido_detalle` →
producción completa → se crea `entrega`.

**Numeración:** Usar `sucursal_contador_pedido` con `SELECT FOR UPDATE`.

---

### pedido_detalle
Líneas de producto dentro de un pedido.

| columna | tipo | null | descripción |
|---|---|---|---|
| id_pedido_detalle | integer | NO | PK |
| empresa_id | bigint | NO | FK → empresa |
| sucursal_id | bigint | NO | FK → sucursal |
| pedido_id | bigint | NO | FK → pedido. UNIQUE con producto_id |
| producto_id | bigint | NO | FK → producto. UNIQUE con pedido_id |
| cantidad | numeric(12,2) | NO | |
| precio_unitario | numeric(12,2) | NO | **Snapshot** — precio real cobrado |
| iva_unitario | numeric(12,2) | SÍ | **Snapshot** — IVA real cobrado |
| subtotal | numeric(12,2) | NO | cantidad × precio_unitario |

**Nota:** `precio_unitario` e `iva_unitario` son snapshots inmutables.

---

### sucursal_contador_pedido
Contador atómico para numeración de pedidos por sucursal. PK compuesta (empresa_id, sucursal_id).

| columna | tipo | null | descripción |
|---|---|---|---|
| empresa_id | bigint | NO | PK. FK → empresa |
| sucursal_id | bigint | NO | PK. FK → sucursal |
| ultimo_pedido | bigint | NO | Último número asignado |
| updated_at | timestamp | SÍ | |

**Uso:** `SELECT ultimo_pedido ... FOR UPDATE` → incrementar → usar el nuevo valor.

---

### estado_pago
Catálogo de estados de pago.

| columna | tipo | null | descripción |
|---|---|---|---|
| id_estado_pago | integer | NO | PK |
| codigo | varchar(30) | SÍ | UNIQUE. Ej: 'PENDIENTE', 'APROBADO', 'RECHAZADO', 'REEMBOLSADO' |
| nombre | varchar(50) | SÍ | |

---

### pago
Registro de pago asociado a un pedido. Un pedido tiene máximo un pago (UNIQUE pedido_id).

| columna | tipo | null | descripción |
|---|---|---|---|
| id_pago | integer | NO | PK |
| empresa_id | bigint | NO | FK → empresa |
| pedido_id | bigint | NO | FK → pedido. UNIQUE |
| proveedor | varchar(50) | NO | 'wompi', 'payu', 'mercadopago', 'manual' |
| referencia | varchar(120) | SÍ | Referencia interna. UNIQUE |
| transaccion_id | varchar(120) | SÍ | ID de la pasarela. UNIQUE |
| moneda | varchar(10) | NO | 'COP', 'USD', etc. |
| monto | numeric(12,2) | NO | |
| metodo_pago | varchar(100) | NO | 'tarjeta', 'pse', 'efectivo', 'transferencia' |
| checkouturl | text | SÍ | URL de pago para redirigir al cliente |
| raw_respuesta | text | SÍ | JSON crudo de la pasarela |
| estado_pago_id | integer | SÍ | FK → estado_pago |
| fecha_pago | timestamp | NO | |
| created_at | timestamp | NO | |
| updated_at | timestamp | SÍ | |

---

### factura
Factura generada para un pedido. Un pedido tiene máximo una factura (UNIQUE pedido_id).

| columna | tipo | null | descripción |
|---|---|---|---|
| id_factura | integer | NO | PK |
| empresa_id | bigint | NO | FK → empresa. UNIQUE con numero_factura |
| pedido_id | bigint | NO | FK → pedido. UNIQUE |
| numero_factura | varchar(50) | NO | UNIQUE por empresa |
| fecha_factura | timestamp | NO | DEFAULT now() |
| total_factura | numeric(14,2) | NO | |
| created_at | timestamp | NO | DEFAULT now() |
| updated_at | timestamp | SÍ | |

---

### estado_produccion
Catálogo de estados del proceso de producción.

| columna | tipo | null | descripción |
|---|---|---|---|
| id_estado_produccion | integer | NO | PK |
| codigo | varchar(30) | NO | UNIQUE. Ej: 'PENDIENTE', 'EN_PROCESO', 'LISTO', 'CANCELADO' |
| nombre | varchar(50) | NO | |
| orden | integer | SÍ | |
| created_at | timestamp | SÍ | DEFAULT CURRENT_TIMESTAMP |

---

### transicion_estado_produccion
Transiciones válidas de estado de producción por empresa.

| columna | tipo | null | descripción |
|---|---|---|---|
| id_trans_estado_prod | integer | NO | PK |
| empresa_id | bigint | NO | FK → empresa. UNIQUE con estado_origen_id+estado_destino_id |
| estado_origen_id | bigint | NO | |
| estado_destino_id | bigint | NO | |
| created_at | timestamp | NO | |

---

### produccion
Orden de producción por ítem de pedido. Un registro por cada `pedido_detalle` aprobado.

| columna | tipo | null | descripción |
|---|---|---|---|
| id_produccion | integer | NO | PK |
| empresa_id | bigint | NO | FK → empresa |
| sucursal_id | bigint | NO | FK → sucursal |
| pedido_id | bigint | SÍ | FK → pedido |
| pedido_detalle_id | bigint | SÍ | FK → pedido_detalle |
| empleado_id | bigint | SÍ | FK → empleado. Debe tener perfil_florista |
| estado_produccion_id | bigint | SÍ | FK → estado_produccion |
| fecha_programada_produccion | date | SÍ | |
| fecha_asignacion | timestamp | SÍ | Cuándo se asignó el florista |
| fecha_inicio | timestamp | SÍ | Cuándo empezó a trabajar |
| fecha_finalizacion | timestamp | SÍ | Cuándo terminó |
| fecha_fin | timestamp | SÍ | **Legacy** — usar fecha_finalizacion |
| tiempoestimadomin | integer | SÍ | Minutos estimados (de producto.tiempo_base_min) |
| tiempo_real_min | integer | SÍ | Minutos reales registrados |
| prioridad | varchar(20) | SÍ | 'baja', 'normal', 'alta', 'urgente' |
| orden_produccion | bigint | SÍ | Orden en la cola del florista |
| observacionesinternas | text | SÍ | |
| created_at | timestamp | NO | |
| updated_at | timestamp | SÍ | |

**Regla:** Al asignar `empleado_id`, verificar que exista en `perfil_florista`
y no esté en incapacidad (`fecha_ini_incap` <= hoy <= `fecha_fin_incap`).

---

### produccion_historial
Auditoría de reasignaciones de florista en producción.

| columna | tipo | null | descripción |
|---|---|---|---|
| id_produccion_historial | integer | NO | PK |
| empresa_id | bigint | NO | FK → empresa |
| sucursal_id | bigint | NO | FK → sucursal |
| produccion_id | bigint | NO | FK → produccion |
| florista_anterior_id | bigint | SÍ | FK → empleado |
| florista_nuevo_id | bigint | SÍ | FK → empleado |
| fecha_cambio | timestamp | NO | |
| motivo | text | NO | |
| usuariocambio | varchar(120) | NO | Login del usuario que hizo el cambio |

---

### estado_entrega
Catálogo de estados del proceso de entrega.

| columna | tipo | null | descripción |
|---|---|---|---|
| id_estado_entrega | integer | NO | PK |
| codigo | varchar(30) | NO | UNIQUE. Ej: 'PENDIENTE', 'ASIGNADO', 'EN_RUTA', 'ENTREGADO', 'NO_ENTREGADO', 'REPROGRAMADO' |
| nombre | varchar(50) | NO | |
| orden | integer | SÍ | |
| created_at | timestamp | SÍ | DEFAULT now() |

---

### transicion_estado_entrega
Transiciones válidas de estado de entrega por empresa.

| columna | tipo | null | descripción |
|---|---|---|---|
| id_tran_estado_ent | integer | NO | PK |
| empresa_id | bigint | NO | FK → empresa. UNIQUE con estado_origen_id+estado_destino_id |
| estado_origen_id | bigint | NO | |
| estado_destino_id | bigint | NO | |
| created_at | timestamp | NO | |

---

### entrega
Intento de entrega de un pedido. Un pedido puede tener múltiples intentos (una fila por intento).

| columna | tipo | null | descripción |
|---|---|---|---|
| id_entrega | integer | NO | PK |
| empresa_id | bigint | NO | FK → empresa |
| sucursal_id | bigint | SÍ | Sucursal que despacha |
| pedido_id | bigint | NO | FK → pedido |
| produccionid | bigint | SÍ | FK → produccion |
| domiciliarioid | bigint | SÍ | FK → empleado. Domiciliario asignado |
| empleado_id | bigint | SÍ | FK → empleado. Quien registró la entrega |
| estadoentregaid | bigint | NO | FK → estado_entrega |
| intentonumero | integer | NO | Número del intento (1, 2, 3...) |
| tipoentrega | varchar(30) | SÍ | 'domicilio', 'recogida_en_tienda' |
| destinatario | varchar(200) | SÍ | Nombre de quien recibe |
| telefonodestino | varchar(30) | SÍ | |
| direccion | varchar(250) | SÍ | |
| barrioid | bigint | SÍ | ID del barrio (snapshot) |
| barrionombre | varchar(150) | SÍ | **Snapshot** — nombre del barrio al momento de la entrega |
| fechaentregaprogramada | timestamp | SÍ | Fecha comprometida con el cliente |
| rangohora | varchar(100) | SÍ | Ej: '2pm - 4pm' |
| fechaasignacion | timestamp | SÍ | Cuando se asignó al domiciliario |
| fechasalida | timestamp | SÍ | Cuando salió a entregar |
| fechaentrega | timestamp | SÍ | Cuando se completó la entrega |
| mensaje | text | SÍ | Mensaje en la tarjeta del arreglo |
| firma | varchar(150) | SÍ | **Legacy** — usar firmaimagenurl |
| firmanombre | varchar(180) | SÍ | Nombre de quien firmó |
| firmadocumento | varchar(50) | SÍ | Documento de quien firmó |
| firmaimagenurl | text | SÍ | URL de la imagen de la firma |
| evidenciafotourl | text | SÍ | URL de foto como evidencia de entrega |
| latituddestino | numeric(10,7) | SÍ | Coordenada snapshot del destino usada para cálculo de distancia |
| longituddestino | numeric(10,7) | SÍ | Coordenada snapshot del destino usada para cálculo de distancia |
| latitudentrega | numeric(10,7) | SÍ | GPS donde se realizó la entrega |
| longitudentrega | numeric(10,7) | SÍ | |
| motivonoentregado | text | SÍ | Razón si no se pudo entregar |
| observaciones | text | SÍ | |
| observaciongeneral | text | SÍ | |
| reprogramadapara | timestamp | SÍ | Nueva fecha si se reprogramó |
| createdat | timestamp | NO | |
| updatedat | timestamp | SÍ | |

**Regla:** Para el estado actual de entrega tomar la fila con mayor `intentonumero`.
`barrionombre`, `latituddestino` y `longituddestino` son snapshots intencionales — no actualizar.

---

### insumo
Materiales usados en producción. Definidos por empresa.

| columna | tipo | null | descripción |
|---|---|---|---|
| id_insumo | integer | NO | PK |
| empresa_id | bigint | NO | FK → empresa. UNIQUE con nombre_insumo y con codigo_barra |
| nombre_insumo | varchar(200) | NO | UNIQUE por empresa |
| codigo_barra | varchar(100) | SÍ | UNIQUE por empresa |
| unidad_medida | varchar(50) | NO | 'unidad', 'tallo', 'metro', 'kg', etc. |
| proveedor_id | integer | SÍ | FK → proveedor. Proveedor principal |
| activo | boolean | NO | DEFAULT true |
| created_at | timestamp | NO | DEFAULT now() |
| updated_at | timestamp | SÍ | |

---

### inventario
Stock actual de un insumo en una sucursal específica. UNIQUE por (sucursal_id, insumo_id).

| columna | tipo | null | descripción |
|---|---|---|---|
| id_inventario | integer | NO | PK |
| empresa_id | bigint | SÍ | FK → empresa |
| sucursal_id | bigint | NO | FK → sucursal. UNIQUE con insumo_id |
| insumo_id | bigint | NO | FK → insumo. UNIQUE con sucursal_id |
| stock_actual | numeric(12,4) | NO | |
| stock_reservado | numeric(12,4) | NO | Stock comprometido en producciones activas |
| stock_minimo | numeric(12,2) | NO | Alerta de reabastecimiento |
| valor_unitario | numeric(12,2) | NO | Costo unitario actual |
| activo | boolean | NO | |
| fechaultimaactualizacion | timestamp | SÍ | |
| created_at | timestamp | NO | |
| updated_at | timestamp | SÍ | |

**Stock disponible real:** `stock_actual - stock_reservado`

---

### tipo_movimiento
Catálogo de tipos de movimiento de inventario.

| columna | tipo | null | descripción |
|---|---|---|---|
| id_tipo_movimiento | integer | NO | PK |
| codigo | varchar(20) | SÍ | UNIQUE. Ej: 'COMPRA', 'CONSUMO', 'AJUSTE_ENT', 'AJUSTE_SAL', 'DEVOLUCION' |
| nombre | varchar(50) | SÍ | |
| afecta_stock | boolean | NO | Si modifica stock_actual |
| signo | smallint | NO | +1 (entrada) o -1 (salida) |

---

### movimiento_inventario
Log de todos los cambios de stock. Registro inmutable — nunca editar ni borrar.

| columna | tipo | null | descripción |
|---|---|---|---|
| id_movimiento | integer | NO | PK |
| empresa_id | bigint | NO | FK → empresa |
| inventario_id | bigint | NO | FK → inventario |
| tipo_movimiento_id | integer | SÍ | FK → tipo_movimiento |
| cantidad | numeric(12,2) | NO | Positivo siempre — el signo lo da tipo_movimiento.signo |
| fecha | timestamp | NO | |
| motivo | varchar(250) | SÍ | |
| usuario_id | bigint | SÍ | FK → usuario. Quién lo registró |
| created_at | timestamp | SÍ | |

---

### proveedor
Proveedores de insumos.

| columna | tipo | null | descripción |
|---|---|---|---|
| id_proveedor | integer | NO | PK |
| nombre_proveedor | varchar(150) | NO | |
| codigo_proveedor | varchar(80) | SÍ | |
| activo | integer | NO | |
| created_at | timestamp | SÍ | |
| updated_at | timestamp | SÍ | |

**Deuda técnica:** Falta `empresa_id` para aislar proveedores por empresa.
Pendiente antes de escalar a múltiples empresas en producción.

---

## Reglas globales para el agente

1. **Siempre filtrar por `empresa_id`** en toda query — excepto cuando `es_superadmin = true`.
   Usar el helper `tenantFilter(user)` antes de construir cualquier query.
2. **Transiciones de estado** — antes de cambiar estado de pedido, producción o entrega,
   validar contra la tabla `transicion_estado_*` correspondiente.
3. **Numeración de pedidos** — usar `sucursal_contador_pedido` con `SELECT FOR UPDATE`.
   Nunca usar `MAX(numero_pedido) + 1`.
4. **Florista disponible** — verificar `perfil_florista` + incapacidad activa +
   `capacidad_diaria` vs producciones del día.
5. **Stock** — al reservar insumos, incrementar `stock_reservado`, no decrementar `stock_actual`.
   Solo decrementar `stock_actual` al confirmar consumo real.
6. **Intentos de entrega** — cada intento es una fila nueva en `entrega` con `intentonumero` incrementado.
7. **Snapshots inmutables** — `pedido_detalle.precio_unitario`, `pedido_detalle.iva_unitario`,
   `entrega.barrionombre`. No actualizar después de la inserción.
8. **Auditoría** — cambios de florista → insertar en `produccion_historial`.
   Acciones sobre usuarios → insertar en `usuario_auditoria`.
9. **Superadmin** — nunca aparece en listados de usuarios de empresa.
   Agregar `AND es_superadmin = false` en toda query que liste usuarios de una empresa.

---

## Deudas técnicas conocidas

| tabla | campo | situación |
|---|---|---|
| empleado | usuario, email, password_hash, last_login | Legacy — autenticación real en tabla usuario |
| proveedor | (sin empresa_id) | Tabla global, pendiente aislar por empresa |
| produccion | fecha_fin | Legacy de fecha_finalizacion — usar fecha_finalizacion |
| entrega | firma | Legacy — usar firmaimagenurl |

No eliminar estos campos — pueden tener datos en producción.
Documentar su deprecación en el código con comentario `// @deprecated`.
