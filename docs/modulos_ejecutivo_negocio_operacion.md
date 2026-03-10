# Resumen Ejecutivo (1 pagina)

## Objetivo del sistema

PetalOps centraliza la operacion diaria de la floristeria en un flujo unico: **Pedido -> Produccion -> Domicilio -> Entrega**.
Adicionalmente, permite administrar usuarios y permisos por empresa para operar como SaaS multi-tenant.

## Que resuelve para negocio

- Reduce tiempos de coordinacion entre areas.
- Mejora trazabilidad de cada pedido hasta la entrega final.
- Estandariza la gestion de equipos (produccion, domicilios, administracion).
- Disminuye errores operativos con reglas y estados controlados.
- Permite crecimiento por empresas/sucursales con control de acceso.

## Modulos y valor operativo

### 1) Pedidos
- Centraliza pedidos en una sola vista.
- Permite aprobar/rechazar con control de estado.
- Facilita consulta de detalle y soporte al cliente.

Impacto: mejor velocidad de atencion y menor reproceso comercial.

### 2) Produccion
- Organiza carga de trabajo de floristas.
- Soporta asignacion y reasignacion con historial.
- Controla avance por estados hasta quedar listo para entregar.

Impacto: mayor cumplimiento de tiempos y balance de capacidad.

### 3) Domicilios
- Administra ultima milla (asignacion, salida a ruta, entrega).
- Registra evidencia de entrega y casos no entregados.
- Permite trazabilidad completa por pedido.

Impacto: mejor experiencia del cliente y control de calidad en entrega.

### 4) Gestion de Usuarios
- Crea/activa/inactiva usuarios.
- Separa gobierno global JOIN vs administracion por empresa.
- Evita accesos indebidos por perfil.

Impacto: operacion segura y escalable por niveles.

## Modelo de gobierno (SaaS)

- **Nivel global JOIN**:
  - Vista global de empresas.
  - Gobierno central del sistema.

- **Nivel empresa**:
  - Administra operacion de su propia empresa.
  - No puede gestionar otras empresas.

- **Nivel operativo**:
  - Ejecuta tareas diarias segun su rol (pedidos, produccion, domicilios).

## Flujo operativo recomendado

1. Pedido se registra y valida.
2. Pedido se aprueba.
3. Produccion asigna y ejecuta.
4. Al estar listo, pasa a Domicilios.
5. Domicilio entrega con evidencia o registra no-entrega.
6. Gestion de usuarios mantiene equipo activo y con permisos correctos.

## KPIs sugeridos para seguimiento gerencial

- Pedidos aprobados por dia.
- Tiempo promedio Pedido -> ParaEntrega.
- Entregas exitosas en primer intento.
- Porcentaje de no-entrega y principales motivos.
- Productividad por florista (tiempo estimado vs real).
- Usuarios activos por empresa/sucursal.

## Riesgos operativos que el sistema ayuda a controlar

- Sobrecarga de produccion en pocos recursos.
- Pedidos sin seguimiento entre areas.
- Entregas sin evidencia o sin trazabilidad.
- Accesos no autorizados a funciones sensibles.

## Proximos pasos de madurez recomendados

1. Tablero ejecutivo semanal con KPIs y alertas.
2. Acuerdos de nivel de servicio internos por etapa (pedido, produccion, entrega).
3. Ciclo mensual de mejora continua por causas de no-entrega y reprocesos.
