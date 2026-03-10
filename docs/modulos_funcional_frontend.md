# Modulos - Guia Funcional Frontend

Documento funcional orientado a producto/UX para operacion desde el front (Petalops).

## 1) Inicio de sesion

### Objetivo
Permitir acceso por usuario unico sin pedir empresa al usuario final.

### Experiencia esperada
1. Usuario ingresa `usuario` + `password`.
2. Si credenciales son validas, front guarda token.
3. Front consulta `/auth/me` y arma navegacion por permisos.

### Comportamiento UX
- Mensaje claro si credenciales fallan.
- No mostrar modulos sin `puedeVer`.
- Redireccion inicial segun modulos disponibles.

## 2) Modulo Pedidos (vista operativa)

### Para que sirve
- Buscar y gestionar pedidos diarios.
- Aprobar/rechazar rapidamente.
- Consultar detalle y descargar factura.

### Flujo funcional
1. Filtrar por estado, fechas, texto.
2. Abrir detalle del pedido.
3. Ejecutar accion:
   - Aprobar
   - Rechazar (con motivo)
   - Descargar factura (si aplica)

### Resultado esperado
- Tabla se actualiza sin recargar toda la app.
- Estado visible con badge consistente.

## 3) Modulo Produccion

### Para que sirve
- Coordinar carga de trabajo de floristas y avance de pedidos.

### Subvistas funcionales
- `Pedidos`: listado de producciones y acciones.
- `Historial`: trazabilidad de reasignaciones.
- `Gestion incapacidad`: estados de florista y impacto.
- `Looker`: tablero embebido de analitica.

### Flujo funcional principal
1. Abrir Produccion.
2. Revisar pedidos pendientes/en curso.
3. Asignar o reasignar florista.
4. Cambiar estado de produccion segun etapa.
5. Consultar historial para auditoria.

### Comportamiento UX
- Sidebar con submenu de Produccion.
- Drawer lateral para acciones por pedido.
- Capsulas mobile para operacion en pantallas pequenas.

## 4) Modulo Domicilios

### Para que sirve
- Gestionar ultima milla y evidencia de entrega.

### Vistas funcionales
- `Vista Admin`: asignacion y monitoreo.
- `Vista Domiciliario`: ejecucion en campo.

### Flujo funcional admin
1. Filtrar entregas (hoy, manana, pendientes, en ruta, no entregado).
2. Asignar domiciliario.
3. Marcar salida a ruta.

### Flujo funcional domiciliario
1. Ver entregas asignadas.
2. Abrir Maps / llamar / WhatsApp.
3. Marcar `Entregado` con evidencia o `NoEntregado` con motivo.

### Resultado esperado
- Trazabilidad completa por entrega.
- Estados sincronizados con Produccion.

## 5) Gestion de Usuarios

### Para que sirve
- Administrar usuarios internos del sistema.

### Diferencia por perfil

#### SuperAdmin global JOIN
- Puede ver selector de empresa.
- Puede operar consola global.
- Ve columna empresa en tabla.

#### Admin de empresa
- Solo ve su empresa (campo fijo de solo lectura).
- No accede a catalogo global de empresas.
- No puede crear roles estructurales.

### Flujo funcional
1. Filtrar por sucursal/estado/busqueda.
2. Crear usuario con rol permitido.
3. Activar/inactivar usuarios existentes.

### Comportamiento UX esperado
- Acciones ocultas o deshabilitadas segun permisos.
- Mensaje explicito cuando no existan roles operativos disponibles.

## 6) Reglas de navegacion entre modulos

### Principio
La navegacion depende de permisos de `auth/me`, no de hardcodes en UI.

### Reglas UX
- Si no tiene acceso a vista actual, redirigir a la siguiente valida.
- Mostrar item `Gestion Usuarios` cuando `canUsuariosPanel=true`.
- Mantener coherencia entre desktop sidebar y mobile menu.

## 7) Casos funcionales sugeridos para QA front

1. Login exitoso con superadmin y empresa-admin.
2. Verificar items de menu por perfil.
3. En Gestion Usuarios:
   - Superadmin ve selector empresa.
   - Empresa-admin no lo ve editable.
4. Intento de crear usuario con rol no permitido debe bloquearse.
5. Flujo pedido -> produccion -> domicilios en una jornada completa.

## 8) Mensajeria y errores (UX)

### Recomendaciones
- `400`: mostrar mensaje de regla de negocio incumplida.
- `403`: mostrar "no tienes permisos para esta accion".
- `500/503`: mostrar mensaje operativo y opcion de reintentar.

### Buenas practicas
- Mantener feedback inmediato tras cada accion.
- Evitar formularios que permitan enviar datos invalidos.
- Priorizar claridad de estado sobre densidad visual.
