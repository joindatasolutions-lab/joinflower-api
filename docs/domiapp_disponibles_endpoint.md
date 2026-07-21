# Contrato DomiApp - Pedidos Disponibles

Endpoint para la vista **Disponibles** de DomiApp. Devuelve pedidos sin asignar a domiciliario, listos para que el domiciliario pueda tomarlos.

No incluye pedidos de recogida en tienda. El backend excluye esos pedidos por `tipoEntrega` y tambien cuando la direccion viene como `Recoger En Tienda`.

## Endpoint

```http
GET /api/domicilios/pedidos/disponibles
```

## Endpoint Alterno Usado Por La Vista Mobile

Algunas pantallas de DomiApp consumen la ruta con guion:

```http
GET /api/domicilios/pedidos-disponibles
```

Esa ruta devuelve un objeto con `items` y `total`:

```json
{
  "items": [
    {
      "idEntrega": 123,
      "pedidoID": 97143,
      "numeroPedido": "FLR-97143",
      "arreglo": "0052 - Bouquet 12 Rosas Rojas",
      "imageUrl": "https://cdn.example.com/producto.jpg",
      "destinatario": "Rashidd",
      "direccion": "Calle 47 # 19-141",
      "barrio": "Cevillar",
      "zona": "Zona 2",
      "horaEntrega": "09:00"
    }
  ],
  "total": 1
}
```

Para esta ruta, el front debe leer `response.items`.

## Autenticacion

```http
Authorization: Bearer <token>
```

## Query Params

| Parametro | Tipo | Requerido | Descripcion |
|---|---:|---:|---|
| `empresaID` | number | Si | Empresa autenticada. |
| `sucursalID` | number | No | Filtra por sucursal. |
| `fecha` | string `YYYY-MM-DD` | No | Fecha de entrega a consultar. |
| `fechaDesde` | string `YYYY-MM-DD` | No | Inicio de rango si no se usa `fecha`. |
| `fechaHasta` | string `YYYY-MM-DD` | No | Fin de rango si no se usa `fecha`. |
| `page` | number | No | Pagina. Default: `1`. |
| `pageSize` | number | No | Tamano de pagina. Max: `200`. |

## Ejemplo Request

```http
GET /api/domicilios/pedidos/disponibles?empresaID=3&sucursalID=3&fecha=2026-07-17&page=1&pageSize=200
Authorization: Bearer <token>
```

## Ejemplo Response

```json
[
  {
    "id": 97143,
    "idEntrega": 123,
    "pedidoID": 97143,
    "produccionID": 456,
    "numeroPedido": "FLR-97143",
    "codigoPedido": "FLR-97143",
    "arreglo": "0052 - Bouquet 12 Rosas Rojas",
    "nombreArreglo": "0052 - Bouquet 12 Rosas Rojas",
    "producto": "0052 - Bouquet 12 Rosas Rojas",
    "productos": ["0052 - Bouquet 12 Rosas Rojas"],
    "imageUrl": "https://cdn.example.com/producto.jpg",
    "imagenUrl": "https://cdn.example.com/producto.jpg",
    "imagenProductoUrl": "https://cdn.example.com/producto.jpg",
    "cliente": "Rashidd bojanini Yance",
    "destinatario": "Rashidd",
    "telefonoDestino": "3001234567",
    "telefonoDestinatario": "3001234567",
    "celularDestinatario": "3001234567",
    "direccion": "Calle 47 # 19-141",
    "barrioId": 10,
    "nombreBarrio": "Cevillar",
    "barrio": "Cevillar",
    "zonaId": 2,
    "nombreZona": "Zona 2",
    "zona": "Zona 2",
    "fechaEntregaProgramada": "2026-07-17T09:00:00",
    "horaEntrega": "09:00",
    "mensaje": "Texto tarjeta",
    "observacion": "Observaciones",
    "estado": "SIN_ASIGNAR",
    "prioridad": "ALTA",
    "latitudDestino": 10.9876543,
    "longitudDestino": -74.1234567
  }
]
```

## Campos Para Pintar La Card

```js
const numero = item.codigoPedido || item.numeroPedido;
const arreglo = item.arreglo || item.nombreArreglo || item.producto || item.productos?.join(", ");
const imagen = item.imageUrl || item.imagenUrl || item.imagenProductoUrl;
const celular = item.celularDestinatario || item.telefonoDestinatario || item.telefonoDestino;
const barrio = item.barrio || item.nombreBarrio;
const zona = item.zona || item.nombreZona;
```

## Asignacion

Para tomar/asignar un pedido disponible, usar:

```js
item.id
```

En este endpoint `id` corresponde al `pedidoID`.

## Imagen Del Producto

La imagen se toma del catalogo de la sucursal:

```txt
petalops.producto_sucursal.imagen_url
```

El backend la expone en tres aliases equivalentes para facilitar integracion:

```js
item.imageUrl
item.imagenUrl
item.imagenProductoUrl
```
