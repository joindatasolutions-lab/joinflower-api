## barrio
| columna | tipo | null | descripción |
|---|---|---|---|
| id_barrio | integer | NO | PK |
| empresa_id | bigint | NO | FK → empresa |
| sucursal_id | bigint | SÍ | FK → sucursal |
| zona_id | bigint | NO |  |
| nombre_barrio | character varying(150) | NO |  |
| costo_domicilio | numeric | NO |  |
| activo | integer | NO |  |
| created_at | timestamp without time zone | NO |  |
| updated_at | timestamp without time zone | SÍ |  |
## caja
| columna | tipo | null | descripción |
|---|---|---|---|
| id_caja | bigint | NO | PK |
| empresa_id | bigint | NO | FK → empresa |
| sucursal_id | bigint | NO | FK → sucursal |
| fecha | date | NO |  |
| base | numeric | NO |  |
| efectivo | numeric | NO |  |
| gasto | numeric | NO |  |
| total_efectivo | numeric | NO |  |
| guardado | numeric | NO |  |
| nueva_base | numeric | NO |  |
| observacion | text | SÍ |  |
| usuario_id | bigint | SÍ | FK → usuario |
| created_at | timestamp without time zone | NO |  |
| updated_at | timestamp without time zone | SÍ |  |
## canal_venta
| columna | tipo | null | descripción |
|---|---|---|---|
| id_canal_venta | bigint | NO | PK |
| empresa_id | bigint | NO |  |
| codigo | character varying(80) | NO |  |
| nombre | character varying(120) | NO |  |
| orden | integer | NO |  |
| activo | boolean | NO |  |
| created_at | timestamp without time zone | NO |  |
| updated_at | timestamp without time zone | SÍ |  |
## categoria
| columna | tipo | null | descripción |
|---|---|---|---|
| id_categoria | bigint | NO | PK |
| empresa_id | bigint | NO | FK → empresa |
| nombre | character varying(120) | NO |  |
| created_at | timestamp with time zone | NO |  |
| activo | boolean | NO |  |
## cliente
| columna | tipo | null | descripción |
|---|---|---|---|
| cliente_id | integer | NO | PK |
| empresa_id | bigint | NO | FK → empresa |
| tipo_ident | character varying(30) | SÍ |  |
| identificacion | character varying(50) | NO |  |
| indicativo | character varying(10) | SÍ |  |
| telefono_completo | character varying(40) | SÍ |  |
| nombre_completo | character varying(200) | NO |  |
| telefono | character varying(30) | SÍ |  |
| email | character varying(150) | SÍ |  |
| activo | integer | NO |  |
| created_at | timestamp without time zone | NO |  |
| updated_at | timestamp without time zone | SÍ |  |
| fecha_cumpleanos | date | SÍ |  |
| fecha_aniversario | date | SÍ |  |
## domicilio_auditoria
| columna | tipo | null | descripción |
|---|---|---|---|
| id_audit | bigint | NO | PK |
| empresa_id | bigint | NO |  |
| sucursal_id | bigint | SÍ |  |
| pedido_id | bigint | NO |  |
| entrega_id | bigint | NO |  |
| actor_user_id | bigint | SÍ |  |
| actor_login | character varying(120) | NO |  |
| domiciliario_id | bigint | SÍ |  |
| accion | character varying(60) | NO |  |
| estado_anterior | character varying(40) | SÍ |  |
| estado_nuevo | character varying(40) | SÍ |  |
| detalle_json | text | SÍ |  |
| created_at | timestamp without time zone | NO |  |
## domicilio_novedad
| columna | tipo | null | descripción |
|---|---|---|---|
| id_novedad | bigint | NO | PK |
| empresa_id | bigint | NO | FK → empresa |
| sucursal_id | bigint | SÍ | FK → sucursal |
| pedido_id | bigint | NO | FK → pedido |
| entrega_id | bigint | NO | FK → entrega |
| domiciliario_id | bigint | SÍ | FK → empleado |
| tipo_novedad | character varying(60) | NO |  |
| motivo | character varying(180) | SÍ |  |
| descripcion | text | SÍ |  |
| evidencia_foto_url | text | SÍ |  |
| estado | character varying(20) | NO |  |
| reportada_en | timestamp without time zone | NO |  |
| reportada_por_login | character varying(120) | SÍ |  |
| auditoria_reporte_id | bigint | SÍ | FK → domicilio_auditoria |
| resuelta_en | timestamp without time zone | SÍ |  |
| resuelta_por_login | character varying(120) | SÍ |  |
| resuelta_por_empleado_id | bigint | SÍ | FK → empleado |
| solucion | text | SÍ |  |
| observaciones_resolucion | text | SÍ |  |
| resultado_pedido_estado | character varying(40) | SÍ |  |
| auditoria_resolucion_id | bigint | SÍ | FK → domicilio_auditoria |
| created_at | timestamp without time zone | NO |  |
| updated_at | timestamp without time zone | SÍ |  |
## empleado
| columna | tipo | null | descripción |
|---|---|---|---|
| id_empleado | integer | NO | PK |
| empresa_id | bigint | NO | FK → empresa |
| sucursal_id | bigint | SÍ | FK → sucursal |
| nombre_empleado | character varying(150) | NO |  |
| cargo | character varying(100) | NO |  |
| activo | integer | NO |  |
| created_at | timestamp without time zone | NO |  |
| updated_at | timestamp without time zone | SÍ |  |
| usuario | character varying(120) | SÍ |  |
| email | character varying(255) | SÍ |  |
| password_hash | character varying(255) | SÍ |  |
| identificacion | character varying(50) | SÍ |  |
| last_login | timestamp without time zone | SÍ |  |
| usuario_id | bigint | SÍ | FK → usuario |
| is_superuser | integer | SÍ |  |
| foto_url | text | SÍ |  |
| vehiculo | character varying(80) | SÍ |  |
| telefono | character varying(40) | SÍ |  |
| tipo | character varying(80) | SÍ |  |
| estado | character varying(20) | SÍ |  |
| placa | character varying(20) | SÍ |  |
| detalle_vehiculo | character varying(160) | SÍ |  |
## empresa
| columna | tipo | null | descripción |
|---|---|---|---|
| id_empresa | integer | NO | PK |
| nombre_empresa | character varying(150) | NO |  |
| nit | character varying(30) | NO |  |
| estado | integer | NO |  |
| created_at | timestamp without time zone | NO |  |
| updated_at | timestamp without time zone | NO |  |
| dominio | character varying(120) | SÍ |  |
| slug | character varying(50) | SÍ |  |
| logo_url | character varying(500) | SÍ |  |
| nombre_comercial | character varying(180) | SÍ |  |
| plan_id | bigint | SÍ | FK → plan |
## empresa_menu
| columna | tipo | null | descripción |
|---|---|---|---|
| id_empresa_menu | bigint | NO | PK |
| empresa_id | bigint | NO |  |
| codigo | character varying(80) | NO |  |
| titulo | character varying(120) | NO |  |
| seccion | character varying(80) | NO |  |
| tipo_control | character varying(40) | NO |  |
| opciones_json | jsonb | SÍ |  |
| requerido_aprobacion | boolean | NO |  |
| activo | boolean | NO |  |
| orden | integer | NO |  |
| created_at | timestamp without time zone | NO |  |
| updated_at | timestamp without time zone | SÍ |  |
## empresa_modulo
| columna | tipo | null | descripción |
|---|---|---|---|
| empresa_id | bigint | NO | FK → empresa |
| modulo | character varying(80) | NO | PK |
| activo | integer | NO |  |
| updatedat | timestamp without time zone | NO |  |
## entrega
| columna | tipo | null | descripción |
|---|---|---|---|
| id_entrega | integer | NO | PK |
| empresa_id | bigint | NO | FK → empresa |
| pedido_id | bigint | NO | FK → pedido |
| empleado_id | bigint | SÍ | FK → empleado |
| estadoentregaid | bigint | NO | FK → estado_entrega |
| tipoentrega | character varying(30) | SÍ |  |
| destinatario | character varying(200) | SÍ |  |
| telefonodestino | character varying(30) | SÍ |  |
| direccion | character varying(250) | SÍ |  |
| barrioid | bigint | SÍ |  |
| barrionombre | character varying(150) | SÍ |  |
| fechasalida | timestamp without time zone | SÍ |  |
| fechaentrega | timestamp without time zone | SÍ |  |
| rangohora | character varying(100) | SÍ |  |
| mensaje | text | SÍ |  |
| firma | character varying(150) | SÍ |  |
| observaciongeneral | text | SÍ |  |
| createdat | timestamp without time zone | NO |  |
| updatedat | timestamp without time zone | SÍ |  |
| sucursalid | bigint | SÍ |  |
| produccionid | bigint | SÍ | FK → produccion |
| domiciliarioid | bigint | SÍ | FK → empleado |
| fechaasignacion | timestamp without time zone | SÍ |  |
| fechaentregaprogramada | timestamp without time zone | SÍ |  |
| latitudentrega | numeric | SÍ |  |
| longitudentrega | numeric | SÍ |  |
| firmanombre | character varying(180) | SÍ |  |
| firmadocumento | character varying(50) | SÍ |  |
| firmaimagenurl | text | SÍ |  |
| evidenciafotourl | text | SÍ |  |
| observaciones | text | SÍ |  |
| motivonoentregado | text | SÍ |  |
| intentonumero | integer | NO |  |
| reprogramadapara | timestamp without time zone | SÍ |  |
| latituddestino | numeric | SÍ |  |
| longituddestino | numeric | SÍ |  |
## estado_entrega
| columna | tipo | null | descripción |
|---|---|---|---|
| id_estado_entrega | integer | NO | PK |
| codigo | character varying(30) | NO |  |
| nombre | character varying(50) | NO |  |
| orden | integer | SÍ |  |
| created_at | timestamp without time zone | SÍ |  |
## estado_pago
| columna | tipo | null | descripción |
|---|---|---|---|
| id_estado_pago | integer | NO | PK |
| codigo | character varying(30) | SÍ |  |
| nombre | character varying(50) | SÍ |  |
## estado_pedido
| columna | tipo | null | descripción |
|---|---|---|---|
| id_estado_pedido | integer | NO | PK |
| nombre_estado | character varying(100) | NO |  |
| descripcion | character varying(250) | SÍ |  |
| orden | integer | SÍ |  |
| activo | integer | SÍ |  |
| created_at | timestamp without time zone | SÍ |  |
| updated_at | timestamp without time zone | SÍ |  |
## estado_produccion
| columna | tipo | null | descripción |
|---|---|---|---|
| id_estado_produccion | integer | NO | PK |
| codigo | character varying(30) | NO |  |
| nombre | character varying(50) | NO |  |
| orden | integer | SÍ |  |
| created_at | timestamp without time zone | SÍ |  |
## factura
| columna | tipo | null | descripción |
|---|---|---|---|
| id_factura | integer | NO | PK |
| empresa_id | bigint | NO | FK → empresa |
| pedido_id | bigint | NO | FK → pedido |
| numero_factura | character varying(50) | NO |  |
| fecha_factura | timestamp without time zone | NO |  |
| total_factura | numeric | NO |  |
| created_at | timestamp without time zone | NO |  |
| updated_at | timestamp without time zone | SÍ |  |
## insumo
| columna | tipo | null | descripción |
|---|---|---|---|
| id_insumo | integer | NO | PK |
| empresa_id | bigint | NO | FK → empresa |
| codigo_barra | character varying(100) | SÍ |  |
| nombre_insumo | character varying(200) | NO |  |
| unidad_medida | character varying(50) | NO |  |
| activo | boolean | NO |  |
| created_at | timestamp without time zone | NO |  |
| updated_at | timestamp without time zone | SÍ |  |
| proveedor_id | integer | SÍ | FK → proveedor |
| categoria | character varying(80) | SÍ |  |
| subcategoria | character varying(80) | SÍ |  |
| color | character varying(80) | SÍ |  |
| descripcion | text | SÍ |  |
| tamano | character varying(50) | SÍ |  |
| fecha_vencimiento | date | SÍ |  |
| marca | character varying(100) | SÍ |  |
| precio_venta | numeric | SÍ |  |
## inventario
| columna | tipo | null | descripción |
|---|---|---|---|
| id_inventario | integer | NO | PK |
| sucursal_id | bigint | NO | FK → sucursal |
| stock_actual | numeric | NO |  |
| stock_reservado | numeric | NO |  |
| created_at | timestamp without time zone | NO |  |
| updated_at | timestamp without time zone | SÍ |  |
| stock_minimo | numeric | NO |  |
| valor_unitario | numeric | NO |  |
| activo | boolean | NO |  |
| fechaultimaactualizacion | timestamp without time zone | SÍ |  |
| empresa_id | bigint | SÍ | FK → empresa |
| insumo_id | bigint | NO | FK → insumo |
## metodo_pago_catalogo
| columna | tipo | null | descripción |
|---|---|---|---|
| id_metodo_pago | bigint | NO | PK |
| empresa_id | bigint | NO |  |
| codigo | character varying(80) | NO |  |
| nombre | character varying(120) | NO |  |
| orden | integer | NO |  |
| activo | boolean | NO |  |
| created_at | timestamp without time zone | NO |  |
| updated_at | timestamp without time zone | SÍ |  |
## modulo
| columna | tipo | null | descripción |
|---|---|---|---|
| id_modulo | integer | NO | PK |
| codigo | character varying(50) | NO |  |
| nombre | character varying(100) | SÍ |  |
| descripcion | text | SÍ |  |
## movimiento_inventario
| columna | tipo | null | descripción |
|---|---|---|---|
| id_movimiento | integer | NO | PK |
| empresa_id | bigint | NO | FK → empresa |
| inventario_id | bigint | NO | FK → inventario |
| cantidad | numeric | NO |  |
| fecha | timestamp without time zone | NO |  |
| motivo | character varying(250) | SÍ |  |
| usuario_id | bigint | SÍ | FK → usuario |
| created_at | timestamp without time zone | SÍ |  |
| tipo_movimiento_id | integer | SÍ | FK → tipo_movimiento |
## pago
| columna | tipo | null | descripción |
|---|---|---|---|
| id_pago | integer | NO | PK |
| empresa_id | bigint | NO | FK → empresa |
| pedido_id | bigint | NO | FK → pedido |
| proveedor | character varying(50) | NO |  |
| referencia | character varying(120) | SÍ |  |
| transaccion_id | character varying(120) | SÍ |  |
| moneda | character varying(10) | NO |  |
| monto | numeric | NO |  |
| checkouturl | text | SÍ |  |
| raw_respuesta | text | SÍ |  |
| metodo_pago | character varying(100) | NO |  |
| fecha_pago | timestamp without time zone | NO |  |
| created_at | timestamp without time zone | NO |  |
| updated_at | timestamp without time zone | SÍ |  |
| estado_pago_id | integer | SÍ | FK → estado_pago |
## pago_metodo
| columna | tipo | null | descripción |
|---|---|---|---|
| id_pago_metodo | bigint | NO | PK |
| empresa_id | bigint | NO |  |
| pago_id | bigint | NO | FK → pago |
| pedido_id | bigint | NO | FK → pedido |
| metodo_pago_id | bigint | NO | FK → metodo_pago_catalogo |
| orden | integer | NO |  |
| created_at | timestamp without time zone | NO |  |
| updated_at | timestamp without time zone | SÍ |  |
| monto | numeric | SÍ |  |
## pedido
| columna | tipo | null | descripción |
|---|---|---|---|
| id_pedido | integer | NO | PK |
| empresa_id | bigint | NO | FK → empresa |
| sucursal_id | bigint | NO | FK → sucursal |
| cliente_id | bigint | NO | FK → cliente |
| fecha_pedido | timestamp without time zone | NO |  |
| estado_pedido_id | bigint | NO | FK → estado_pedido |
| version | integer | NO |  |
| motivo_rechazo | character varying(300) | SÍ |  |
| total_bruto | numeric | NO |  |
| total_iva | numeric | NO |  |
| total_neto | numeric | NO |  |
| created_at | timestamp without time zone | NO |  |
| updated_at | timestamp without time zone | SÍ |  |
| numero_pedido | bigint | SÍ |  |
| codigo_pedido | character varying(40) | SÍ |  |
| costo_domicilio | numeric | NO |  |
| domicilio_obsequiado | boolean | NO |  |
| omitir_costo_domicilio | boolean | NO |  |
| domicilio_original | numeric | SÍ |  |
| descuento_domicilio | numeric | SÍ |  |
## pedido_auditoria
| columna | tipo | null | descripción |
|---|---|---|---|
| id_audit | bigint | NO | PK |
| empresa_id | bigint | NO |  |
| sucursal_id | bigint | NO |  |
| pedido_id | bigint | NO |  |
| actor_user_id | bigint | SÍ |  |
| actor_login | character varying(120) | NO |  |
| accion | character varying(60) | NO |  |
| estado_origen_id | bigint | SÍ |  |
| estado_destino_id | bigint | SÍ |  |
| detalle_json | text | SÍ |  |
| created_at | timestamp without time zone | NO |  |
## pedido_canal_venta
| columna | tipo | null | descripción |
|---|---|---|---|
| id_pedido_canal_venta | bigint | NO | PK |
| empresa_id | bigint | NO |  |
| pedido_id | bigint | NO | FK → pedido |
| canal_venta_id | bigint | NO | FK → canal_venta |
| created_at | timestamp without time zone | NO |  |
| updated_at | timestamp without time zone | SÍ |  |
## pedido_detalle
| columna | tipo | null | descripción |
|---|---|---|---|
| id_pedido_detalle | integer | NO | PK |
| empresa_id | bigint | NO | FK → empresa |
| sucursal_id | bigint | NO | FK → sucursal |
| pedido_id | bigint | NO | FK → pedido |
| producto_id | bigint | NO | FK → producto |
| cantidad | numeric | NO |  |
| precio_unitario | numeric | NO |  |
| iva_unitario | numeric | SÍ |  |
| subtotal | numeric | NO |  |
| observaciones_personalizados | text | SÍ |  |
## pedido_whatsapp_outbox
| columna | tipo | null | descripción |
|---|---|---|---|
| id | bigint | NO | PK |
| empresa_id | bigint | NO |  |
| pedido_id | bigint | NO |  |
| estado_origen_id | bigint | SÍ |  |
| estado_destino_id | bigint | NO |  |
| telefono | character varying(30) | SÍ |  |
| nombre_cliente | character varying(200) | SÍ |  |
| codigo_pedido | character varying(40) | SÍ |  |
| status | character varying(20) | NO |  |
| attempts | integer | NO |  |
| last_error | text | SÍ |  |
| available_at | timestamp without time zone | NO |  |
| sent_at | timestamp without time zone | SÍ |  |
| created_at | timestamp without time zone | NO |  |
| updated_at | timestamp without time zone | NO |  |
| empresa_nombre_comercial | character varying(180) | SÍ |  |
| order_number | bigint | SÍ |  |
| product_summary | text | SÍ |  |
| delivery_date | timestamp without time zone | SÍ |  |
| delivery_address | text | SÍ |  |
| total_neto | numeric | SÍ |  |
## perfil_florista
| columna | tipo | null | descripción |
|---|---|---|---|
| empleado_id | bigint | NO | FK → empleado |
| capacidad_diaria | bigint | NO |  |
| trab_simul_permi | integer | NO |  |
| especialidades | text | SÍ |  |
| fecha_ini_incap | timestamp without time zone | SÍ |  |
| fecha_fin_incap | timestamp without time zone | SÍ |  |
| numero_interno | bigint | SÍ |  |
| es_externo | boolean | NO |  |
## permiso_modulo
| columna | tipo | null | descripción |
|---|---|---|---|
| rol_id | bigint | NO | FK → rol |
| modulo | character varying(80) | NO | PK |
| puede_ver | boolean | NO |  |
| puede_crear | boolean | NO |  |
| puede_editar | boolean | NO |  |
| puede_eliminar | boolean | NO |  |
| empresa_id | integer | NO |  |
## plan
| columna | tipo | null | descripción |
|---|---|---|---|
| id_plan | bigint | NO | PK |
| nombre | character varying(100) | NO |  |
| descripcion | character varying(255) | SÍ |  |
| empresa_id | bigint | SÍ | FK → empresa |
## plan_modulo
| columna | tipo | null | descripción |
|---|---|---|---|
| plan_id | bigint | NO | FK → plan |
| modulo | character varying(80) | NO | PK |
| activo | boolean | NO |  |
## produccion
| columna | tipo | null | descripción |
|---|---|---|---|
| id_produccion | integer | NO | PK |
| empresa_id | bigint | NO | FK → empresa |
| sucursal_id | bigint | NO | FK → sucursal |
| pedido_id | bigint | SÍ | FK → pedido |
| fecha_programada_produccion | date | SÍ |  |
| fecha_asignacion | timestamp without time zone | SÍ |  |
| pedido_detalle_id | bigint | SÍ | FK → pedido_detalle |
| empleado_id | bigint | SÍ | FK → empleado |
| estado_produccion_id | bigint | SÍ | FK → estado_produccion |
| fecha_inicio | timestamp without time zone | SÍ |  |
| fecha_finalizacion | timestamp without time zone | SÍ |  |
| tiempoestimadomin | integer | SÍ |  |
| tiempo_real_min | integer | SÍ |  |
| prioridad | character varying(20) | SÍ |  |
| observacionesinternas | text | SÍ |  |
| orden_produccion | bigint | SÍ |  |
| fecha_fin | timestamp without time zone | SÍ |  |
| created_at | timestamp without time zone | NO |  |
| updated_at | timestamp without time zone | SÍ |  |
## produccion_historial
| columna | tipo | null | descripción |
|---|---|---|---|
| id_produccion_historial | integer | NO | PK |
| empresa_id | bigint | NO | FK → empresa |
| sucursal_id | bigint | NO | FK → sucursal |
| produccion_id | bigint | NO |  |
| florista_anterior_id | bigint | SÍ | FK → empleado |
| florista_nuevo_id | bigint | SÍ | FK → empleado |
| fecha_cambio | timestamp without time zone | NO |  |
| motivo | text | NO |  |
| usuariocambio | character varying(120) | NO |  |
## producto
| columna | tipo | null | descripción |
|---|---|---|---|
| id_producto | integer | NO | PK |
| empresa_id | bigint | NO | FK → empresa |
| categoria_id | bigint | NO | FK → categoria |
| codigo_producto | character varying(50) | NO |  |
| nombre_producto | character varying(150) | NO |  |
| descripcion | text | SÍ |  |
| porcentaje_iva | numeric | SÍ |  |
| iva_incluido | boolean | SÍ |  |
| tiempo_base_min | integer | SÍ |  |
| nivel_complejidad | character varying(50) | SÍ |  |
| activo | boolean | NO |  |
| created_at | timestamp without time zone | NO |  |
| updated_at | timestamp without time zone | SÍ |  |
| codigo_catalogo | character varying(100) | SÍ |  |
| image_url | text | SÍ |  |
## producto_sucursal
| columna | tipo | null | descripción |
|---|---|---|---|
| id_producto_sucursal | integer | NO | PK |
| producto_id | integer | NO | FK → producto |
| sucursal_id | bigint | NO | FK → sucursal |
| precio | numeric | NO |  |
| activo | boolean | NO |  |
| es_destacado | boolean | SÍ |  |
| orden_catalogo | integer | SÍ |  |
| imagen_url | character varying(500) | SÍ |  |
| imagen_s3_key | character varying(255) | SÍ |  |
| created_at | timestamp without time zone | NO |  |
| updated_at | timestamp without time zone | SÍ |  |
| imagen_sm_key | character varying(255) | SÍ |  |
| imagen_md_key | character varying(255) | SÍ |  |
| imagen_lg_key | character varying(255) | SÍ |  |
## proveedor
| columna | tipo | null | descripción |
|---|---|---|---|
| id_proveedor | integer | NO | PK |
| nombre_proveedor | character varying(150) | NO |  |
| codigo_proveedor | character varying(80) | SÍ |  |
| activo | integer | NO |  |
| created_at | timestamp without time zone | SÍ |  |
| updated_at | timestamp without time zone | SÍ |  |
| empresa_id | bigint | SÍ | FK → empresa |
| telefono | character varying(30) | SÍ |  |
| email | character varying(150) | SÍ |  |
| direccion | character varying(255) | SÍ |  |
## receta
| columna | tipo | null | descripción |
|---|---|---|---|
| id_receta | bigint | NO | PK |
| empresa_id | bigint | NO | FK → empresa |
| nombre | character varying(200) | NO |  |
| descripcion | text | SÍ |  |
| activo | boolean | NO |  |
| created_at | timestamp without time zone | NO |  |
| updated_at | timestamp without time zone | SÍ |  |
| producto_id | bigint | SÍ | FK → producto |
| capacidad_manual | numeric | SÍ |  |
## receta_detalle
| columna | tipo | null | descripción |
|---|---|---|---|
| id_receta_detalle | bigint | NO | PK |
| empresa_id | bigint | NO | FK → empresa |
| receta_id | bigint | NO | FK → receta |
| inventario_id | bigint | NO | FK → inventario |
| cantidad | numeric | NO |  |
| created_at | timestamp without time zone | NO |  |
## rol
| columna | tipo | null | descripción |
|---|---|---|---|
| id_rol | integer | NO | PK |
| empresa_id | bigint | NO | FK → empresa |
| nombre_rol | character varying(80) | NO |  |
## sucursal
| columna | tipo | null | descripción |
|---|---|---|---|
| id_sucursal | integer | NO | PK |
| empresa_id | bigint | NO | FK → empresa |
| nombre_sucursal | character varying(120) | NO |  |
| direccion | character varying(200) | SÍ |  |
| telefono | character varying(30) | SÍ |  |
| estado | character varying(30) | NO |  |
| created_at | timestamp without time zone | NO |  |
| updated_at | timestamp without time zone | SÍ |  |
| prefijo_pedido | character varying(12) | SÍ |  |
## sucursal_contador_pedido
| columna | tipo | null | descripción |
|---|---|---|---|
| empresa_id | bigint | NO | FK → empresa |
| sucursal_id | bigint | NO | FK → sucursal |
| ultimo_pedido | bigint | NO |  |
| updated_at | timestamp without time zone | SÍ |  |
## tipo_movimiento
| columna | tipo | null | descripción |
|---|---|---|---|
| id_tipo_movimiento | integer | NO | PK |
| codigo | character varying(20) | SÍ |  |
| nombre | character varying(50) | SÍ |  |
| afecta_stock | boolean | NO |  |
| signo | smallint | NO |  |
## transicion_estado_entrega
| columna | tipo | null | descripción |
|---|---|---|---|
| id_tran_estado_ent | integer | NO | PK |
| empresa_id | bigint | NO | FK → empresa |
| estado_origen_id | bigint | NO |  |
| estado_destino_id | bigint | NO |  |
| created_at | timestamp without time zone | NO |  |
## transicion_estado_pedido
| columna | tipo | null | descripción |
|---|---|---|---|
| id_trans_estado_ped | integer | NO | PK |
| empresa_id | bigint | NO | FK → empresa |
| estado_origen_id | bigint | NO |  |
| estado_destino_id | bigint | NO |  |
| created_at | timestamp without time zone | NO |  |
## transicion_estado_produccion
| columna | tipo | null | descripción |
|---|---|---|---|
| id_trans_estado_prod | integer | NO | PK |
| empresa_id | bigint | NO | FK → empresa |
| estado_origen_id | bigint | NO |  |
| estado_destino_id | bigint | NO |  |
| created_at | timestamp without time zone | NO |  |
## usuario
| columna | tipo | null | descripción |
|---|---|---|---|
| id_usuario | integer | NO | PK |
| empresa_id | bigint | SÍ | FK → empresa |
| nombre | character varying(150) | NO |  |
| email | character varying(180) | NO |  |
| passwordhash | character varying(255) | NO |  |
| rolid | bigint | SÍ | FK → rol |
| estado | character varying(20) | NO |  |
| ultimo_login | timestamp without time zone | SÍ |  |
| created_at | timestamp without time zone | SÍ |  |
| updated_at | timestamp without time zone | SÍ |  |
| login | character varying(80) | NO |  |
| sucursal_id | bigint | SÍ |  |
| es_superadmin | boolean | NO |  |
## usuario_auditoria
| columna | tipo | null | descripción |
|---|---|---|---|
| id_audit | integer | NO | PK |
| empresa_id | bigint | NO |  |
| actor_user_id | bigint | NO |  |
| actor_login | character varying(80) | NO |  |
| accion | character varying(60) | NO |  |
| target_user_id | bigint | NO |  |
| target_login | character varying(80) | NO |  |
| detalle_json | text | SÍ |  |
| created_at | timestamp without time zone | NO |  |
## usuario_modulo
| columna | tipo | null | descripción |
|---|---|---|---|
| usuario_id | bigint | NO | FK → usuario |
| modulo | character varying(80) | NO | PK |
| activo | boolean | NO |  |
| updated_at | timestamp without time zone | NO |  |




# Modelo Entidad-Relación — Base de Datos

## Resumen de tablas y relaciones

Este documento describe todas las tablas del sistema y sus relaciones (FKs) para uso del agente.

---

## Entidades principales y su jerarquía

```
plan
 └── empresa (FK → plan)
      ├── sucursal (FK → empresa)
      │    ├── barrio (FK → empresa, sucursal)
      │    ├── caja (FK → empresa, sucursal, usuario)
      │    ├── empleado (FK → empresa, sucursal, usuario)
      │    ├── inventario (FK → empresa, sucursal, insumo)
      │    ├── produccion (FK → empresa, sucursal, pedido, pedido_detalle, empleado, estado_produccion)
      │    ├── produccion_historial (FK → empresa, sucursal, empleado x2)
      │    ├── producto_sucursal (FK → producto, sucursal)
      │    └── sucursal_contador_pedido (FK → empresa, sucursal)
      │
      ├── usuario (FK → empresa, rol)
      │    ├── usuario_modulo (FK → usuario)
      │    └── empleado.usuario_id (FK → usuario)
      │
      ├── rol (FK → empresa)
      │    └── permiso_modulo (FK → rol)
      │
      ├── cliente (FK → empresa)
      │
      ├── pedido (FK → empresa, sucursal, cliente, estado_pedido)
      │    ├── pedido_detalle (FK → empresa, sucursal, pedido, producto)
      │    ├── pedido_canal_venta (FK → pedido, canal_venta)
      │    ├── entrega (FK → empresa, pedido, empleado x2, estado_entrega, produccion)
      │    │    └── domicilio_novedad (FK → empresa, sucursal, pedido, entrega, empleado x2, domicilio_auditoria x2)
      │    ├── pago (FK → empresa, pedido, estado_pago)
      │    │    └── pago_metodo (FK → pago, pedido, metodo_pago_catalogo)
      │    └── factura (FK → empresa, pedido)
      │
      ├── producto (FK → empresa, categoria)
      │    └── receta (FK → empresa, producto)
      │         └── receta_detalle (FK → empresa, receta, inventario)
      │
      ├── insumo (FK → empresa, proveedor)
      │    └── inventario (FK → empresa, sucursal, insumo)
      │         └── movimiento_inventario (FK → empresa, inventario, usuario, tipo_movimiento)
      │
      ├── canal_venta (empresa_id sin FK explícita)
      ├── categoria (FK → empresa)
      ├── empresa_menu (empresa_id sin FK explícita)
      ├── empresa_modulo (FK → empresa)
      ├── metodo_pago_catalogo (empresa_id sin FK explícita)
      ├── transicion_estado_entrega (FK → empresa)
      ├── transicion_estado_pedido (FK → empresa)
      └── transicion_estado_produccion (FK → empresa)
```

---

## Tablas de catálogo (sin FK a empresa)

| Tabla | PK | Descripción |
|---|---|---|
| estado_entrega | id_estado_entrega | Estados posibles de una entrega |
| estado_pago | id_estado_pago | Estados posibles de un pago |
| estado_pedido | id_estado_pedido | Estados posibles de un pedido |
| estado_produccion | id_estado_produccion | Estados posibles de producción |
| modulo | id_modulo | Catálogo de módulos del sistema |
| tipo_movimiento | id_tipo_movimiento | Tipos de movimiento de inventario |
| plan | id_plan | Planes de suscripción |
| plan_modulo | (plan_id, modulo) | Módulos habilitados por plan |

---

## Tablas de auditoría / log

| Tabla | Descripción |
|---|---|
| domicilio_auditoria | Log de acciones sobre entregas/domicilios |
| pedido_auditoria | Log de cambios de estado de pedidos |
| pedido_whatsapp_outbox | Cola de mensajes WhatsApp por pedido |
| usuario_auditoria | Log de acciones sobre usuarios |
| produccion_historial | Historial de reasignación de floristas |

---

## Relaciones detalladas por tabla

### barrio
- `empresa_id` → `empresa.id_empresa`
- `sucursal_id` → `sucursal.id_sucursal`

### caja
- `empresa_id` → `empresa.id_empresa`
- `sucursal_id` → `sucursal.id_sucursal`
- `usuario_id` → `usuario.id_usuario`

### canal_venta
- `empresa_id` (sin FK formal declarada)

### categoria
- `empresa_id` → `empresa.id_empresa`

### cliente
- `empresa_id` → `empresa.id_empresa`

### domicilio_novedad
- `empresa_id` → `empresa.id_empresa`
- `sucursal_id` → `sucursal.id_sucursal`
- `pedido_id` → `pedido.id_pedido`
- `entrega_id` → `entrega.id_entrega`
- `domiciliario_id` → `empleado.id_empleado`
- `auditoria_reporte_id` → `domicilio_auditoria.id_audit`
- `resuelta_por_empleado_id` → `empleado.id_empleado`
- `auditoria_resolucion_id` → `domicilio_auditoria.id_audit`

### empleado
- `empresa_id` → `empresa.id_empresa`
- `sucursal_id` → `sucursal.id_sucursal`
- `usuario_id` → `usuario.id_usuario`

### empresa
- `plan_id` → `plan.id_plan`

### empresa_modulo
- `empresa_id` → `empresa.id_empresa`

### entrega
- `empresa_id` → `empresa.id_empresa`
- `pedido_id` → `pedido.id_pedido`
- `empleado_id` → `empleado.id_empleado`
- `estadoentregaid` → `estado_entrega.id_estado_entrega`
- `produccionid` → `produccion.id_produccion`
- `domiciliarioid` → `empleado.id_empleado`

### factura
- `empresa_id` → `empresa.id_empresa`
- `pedido_id` → `pedido.id_pedido`

### insumo
- `empresa_id` → `empresa.id_empresa`
- `proveedor_id` → `proveedor.id_proveedor`

### inventario
- `empresa_id` → `empresa.id_empresa`
- `sucursal_id` → `sucursal.id_sucursal`
- `insumo_id` → `insumo.id_insumo`

### movimiento_inventario
- `empresa_id` → `empresa.id_empresa`
- `inventario_id` → `inventario.id_inventario`
- `usuario_id` → `usuario.id_usuario`
- `tipo_movimiento_id` → `tipo_movimiento.id_tipo_movimiento`

### pago
- `empresa_id` → `empresa.id_empresa`
- `pedido_id` → `pedido.id_pedido`
- `estado_pago_id` → `estado_pago.id_estado_pago`

### pago_metodo
- `pago_id` → `pago.id_pago`
- `pedido_id` → `pedido.id_pedido`
- `metodo_pago_id` → `metodo_pago_catalogo.id_metodo_pago`

### pedido
- `empresa_id` → `empresa.id_empresa`
- `sucursal_id` → `sucursal.id_sucursal`
- `cliente_id` → `cliente.cliente_id`
- `estado_pedido_id` → `estado_pedido.id_estado_pedido`

### pedido_canal_venta
- `pedido_id` → `pedido.id_pedido`
- `canal_venta_id` → `canal_venta.id_canal_venta`

### pedido_detalle
- `empresa_id` → `empresa.id_empresa`
- `sucursal_id` → `sucursal.id_sucursal`
- `pedido_id` → `pedido.id_pedido`
- `producto_id` → `producto.id_producto`

### perfil_florista
- `empleado_id` → `empleado.id_empleado`

### permiso_modulo
- `rol_id` → `rol.id_rol`

### plan_modulo
- `plan_id` → `plan.id_plan`

### produccion
- `empresa_id` → `empresa.id_empresa`
- `sucursal_id` → `sucursal.id_sucursal`
- `pedido_id` → `pedido.id_pedido`
- `pedido_detalle_id` → `pedido_detalle.id_pedido_detalle`
- `empleado_id` → `empleado.id_empleado`
- `estado_produccion_id` → `estado_produccion.id_estado_produccion`

### produccion_historial
- `empresa_id` → `empresa.id_empresa`
- `sucursal_id` → `sucursal.id_sucursal`
- `florista_anterior_id` → `empleado.id_empleado`
- `florista_nuevo_id` → `empleado.id_empleado`

### producto
- `empresa_id` → `empresa.id_empresa`
- `categoria_id` → `categoria.id_categoria`

### producto_sucursal
- `producto_id` → `producto.id_producto`
- `sucursal_id` → `sucursal.id_sucursal`

### proveedor
- `empresa_id` → `empresa.id_empresa`

### receta
- `empresa_id` → `empresa.id_empresa`
- `producto_id` → `producto.id_producto`

### receta_detalle
- `empresa_id` → `empresa.id_empresa`
- `receta_id` → `receta.id_receta`
- `inventario_id` → `inventario.id_inventario`

### rol
- `empresa_id` → `empresa.id_empresa`

### sucursal
- `empresa_id` → `empresa.id_empresa`

### sucursal_contador_pedido
- `empresa_id` → `empresa.id_empresa`
- `sucursal_id` → `sucursal.id_sucursal`

### transicion_estado_entrega
- `empresa_id` → `empresa.id_empresa`

### transicion_estado_pedido
- `empresa_id` → `empresa.id_empresa`

### transicion_estado_produccion
- `empresa_id` → `empresa.id_empresa`

### usuario
- `empresa_id` → `empresa.id_empresa`
- `rolid` → `rol.id_rol`

### usuario_modulo
- `usuario_id` → `usuario.id_usuario`

---


```