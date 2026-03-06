# Módulo de Producción — Diccionario de Campos (Fuente Única v2)

## 1) Tablas existentes reutilizadas

### `Pedido`
- `idPedido`
- `empresaID`
- `sucursalID`
- `clienteID`
- `fechaPedido`
- `estadoPedidoID`
- `version`
- `totalBruto`
- `totalIva`
- `totalNeto`

### `Entrega`
- `pedidoID`
- `fechaEntrega`
- `rangoHora`
- `destinatario`
- `telefonoDestino`
- `direccion`
- `barrioNombre`
- `mensaje`
- `observacionGeneral`

### `Cliente`
- `idCliente`
- `nombreCompleto`
- `telefono`
- `telefonoCompleto`
- `identificacion`

### `PedidoDetalle`
- `pedidoID`
- `productoID`
- `cantidad`
- `subtotal`

### `Producto`
- `idProducto`
- `nombreProducto`
- `categoriaID`
- `tiempoBaseProduccionMin`
- `nivelComplejidad`

### `EstadoPedido`
- `idEstadoPedido`
- `nombreEstado`

---

## 2) Nuevas tablas / extensiones del módulo

### `Florista`
- `idFlorista` (PK)
- `empresaID` (multi-tenant)
- `sucursalID`
- `nombre`
- `capacidadDiaria`
- `trabajosSimultaneosPermitidos`
- `estado` (`Activo`, `Inactivo`, `Incapacidad`)
- `fechaInicioIncapacidad`
- `fechaFinIncapacidad`
- `activo`
- `especialidades`
- `createdAt`
- `updatedAt`

### `Produccion`
- `idProduccion` (PK)
- `empresaID` (multi-tenant)
- `sucursalID`
- `pedidoID` (FK a `Pedido.idPedido`)
- `floristaID` (FK nullable a `Florista.idFlorista`)
- `fechaProgramadaProduccion`
- `fechaAsignacion`
- `fechaInicio`
- `fechaFinalizacion`
- `tiempoEstimadoMin`
- `tiempoRealMin`
- `estado` (`Pendiente`, `EnProduccion`, `ParaEntrega`, `Cancelado`)
- `prioridad` (`BAJA`, `MEDIA`, `ALTA`)
- `observacionesInternas`
- `ordenProduccion`
- `createdAt`
- `updatedAt`

### `ProduccionHistorial`
- `idProduccionHistorial` (PK)
- `empresaID`
- `sucursalID`
- `produccionID`
- `floristaAnteriorID`
- `floristaNuevoID`
- `fechaCambio`
- `motivo`
- `usuarioCambio`

### Índices recomendados
- `idx_produccion_fecha_estado(fechaProgramadaProduccion, estado)`
- `idx_produccion_florista_fecha(floristaID, fechaProgramadaProduccion)`
- `idx_produccion_empresa_sucursal_fecha(empresaID, sucursalID, fechaProgramadaProduccion)`
- `idx_historial_produccion_fecha(produccionID, fechaCambio)`
- `idx_historial_empresa_sucursal_fecha(empresaID, sucursalID, fechaCambio)`

---

## 3) Reglas operativas implementadas

### Asignación inteligente (justa)
1. Filtra floristas activos.
2. Excluye incapacidad en `fechaProgramadaProduccion`.
3. Valida `carga del día < capacidadDiaria`.
4. Ordena por `ocupacion/capacidad` ascendente.

### Trabajos simultáneos
- Antes de pasar a `EnProduccion` valida:
  - `florista` asignado.
  - `simultáneos en EnProduccion < trabajosSimultaneosPermitidos`.

### Incapacidad
- Cambio de estado de florista a `Incapacidad`:
  - Reasigna automáticamente pendientes futuras.
  - No mueve `EnProduccion` (requiere acción manual).
  - Registra historial por cada reasignación.

### Reasignación auditada
- Endpoint dedicado con `motivo` y `usuarioCambio` obligatorios.
- También se audita reasignación cuando corresponde desde otros flujos.

### Recalculo por cambio de pedido
- Si producción está `Pendiente`:
  - recalcula `tiempoEstimadoMin`.
  - recalcula `fechaProgramadaProduccion`.
  - revalida capacidad del florista y reasigna si hace falta.
- Si está `EnProduccion` y cambia estructura:
  - cancela y crea nueva producción (si la restricción de BD lo permite).
  - incrementa `Pedido.version`.

### Estados estrictos
- Permitidos:
  - `Pendiente -> EnProduccion`
  - `EnProduccion -> ParaEntrega`
  - `Pendiente -> Cancelado`
  - `EnProduccion -> Cancelado`
- Bloqueados:
  - `ParaEntrega -> *`
  - `Cancelado -> *`

---

## 4) Endpoints backend implementados

Base: `/produccion`

- `POST /produccion/generar-desde-pedidos`
- `GET /produccion/floristas`
- `PUT /produccion/floristas/{florista_id}/estado`
- `GET /produccion`
- `GET /produccion/resumen`
- `GET /produccion/kanban`
- `PUT /produccion/{produccion_id}/asignar`
- `PUT /produccion/{produccion_id}/reasignar`
- `PUT /produccion/{produccion_id}/estado`
- `POST /produccion/pedido/{pedido_id}/recalcular`
- `GET /produccion/historial/reasignaciones`
- `GET /produccion/metricas/productividad`
- `GET /produccion/metricas/operacion`

---

## 5) Scripts SQL

- `sql/alter_produccion_module.sql` (base del módulo)
- `sql/alter_produccion_operativa_v2.sql` (endurecimiento operativo)
