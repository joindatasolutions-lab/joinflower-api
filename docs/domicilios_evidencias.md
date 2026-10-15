# Consulta de evidencias del modal de Domicilios

`GET /domicilios/pedidos/{numero_pedido}/evidencias?empresaID=3&sucursalID=3`

Enviar `Authorization: Bearer <token>` de la sesión del panel. Cualquier rol con
permiso `domicilios.puedeVer` y módulo activo puede consultar. Se valida la empresa
y la pertenencia de la sucursal. Usuarios con sucursal asignada quedan limitados
a esa sucursal; administradores de empresa pueden consultar sus sucursales y
administradores globales pueden seleccionar el contexto explícito.

El número corresponde a `pedido.numero_pedido`, no al ID interno ni al código con
prefijo. La consulta relaciona la entrega por pedido y empresa, seleccionando el
último intento (intento descendente y luego ID descendente).

```json
{
  "numero_pedido": 100117,
  "id_pedido": 6589,
  "id_entrega": 6557,
  "estado": "entregado",
  "firma_nombre": "RECEPTOR",
  "firma_documento": "123",
  "observaciones": null,
  "evidencia_entrega_url": "https://example.com/foto.png",
  "evidencia_firma_url": "https://example.com/firma.png"
}
```

Los campos ausentes o vacíos se devuelven como `null`. Un pedido sin entrega o
sin evidencias devuelve 200. Pedido inexistente en el contexto: 404; token ausente
o inválido: 401; sin permiso o contexto no autorizado: 403; fallo SQL: 500.

El frontend debe sustituir la consulta a `/pedidos/historial` por esta ruta y
mostrar una evidencia por cada URL no nula. No se requiere endpoint de subida.
Los valores del ejemplo son ilustrativos; verificar el pedido 100117 en el
ambiente desplegado con una sesión autorizada.
