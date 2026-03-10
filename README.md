# PetalOps API (FastAPI)

Backend para catálogo y gestión de pedidos con arquitectura por capas usando FastAPI + SQLAlchemy sobre MySQL.

## 1) Estructura del proyecto

```text
app/
  database.py
  main.py
  models/
  routers/
  schemas/
  services/
csv/
sql/
tests/
```

### Capas

- **models/**: modelos SQLAlchemy (mapeo de tablas existentes).
- **schemas/**: modelos Pydantic de entrada/salida.
- **services/**: lógica de negocio transaccional.
- **routers/**: endpoints HTTP (delegan lógica en servicios).
- **main.py**: instancia de FastAPI, CORS y registro de routers.

## 2) Requisitos

- Python 3.10+
- Base de datos MySQL accesible
- Dependencias del proyecto instaladas en un entorno virtual

## 3) Configuración de entorno

Este proyecto carga variables desde `.env` (ver `app/database.py`).

Variables requeridas:

```env
DATABASE_HOST=148.113.221.17
DATABASE_PORT=3306
DATABASE_NAME=joindata_app
DATABASE_USER=joindata_joindata
DATABASE_PASSWORD=Emprender2025#
```

Variables para Wompi:

```env
WOMPI_PUBLIC_KEY=pub_test_xxxxxxxxxxxxxxxxxxxx
WOMPI_INTEGRITY_SECRET=test_integrity_xxxxxxxxxx
WOMPI_CURRENCY=COP
WOMPI_REDIRECT_URL=https://petalops.vercel.app/pago-resultado.html
WOMPI_CHECKOUT_BASE_URL=https://checkout.wompi.co/p/
```

Para desarrollo local, WOMPI no acepta `localhost` ni `http`. Expone el frontend con un tunel publico (por ejemplo ngrok o Cloudflare Tunnel) y usa una URL HTTPS, por ejemplo:

```env
WOMPI_REDIRECT_URL=https://your-ngrok-url.ngrok-free.app/pago-resultado.html
```

## 4) Instalación y ejecución

### Instalar dependencias

```powershell
pip install -r requirements.txt
```

> Si no tienes `requirements.txt`, instala al menos: `fastapi`, `uvicorn`, `sqlalchemy`, `pymysql`, `python-dotenv`.

### Ejecutar API

```powershell
uvicorn app.main:app --reload --port 8001
```

### Ejecutar frontend (starter)

Este repositorio incluye un frontend base en `front/` para consumir endpoints del API.

En otra terminal, desde la raiz del proyecto:

```powershell
python -m http.server 5500 -d front
```

Luego abre:

- `http://127.0.0.1:5500`

El starter permite probar:

- `GET /ping`
- `GET /health`
- `GET /empresa/por-slug/{slug}`
- `GET /catalogo/empresa/{empresa_id}`
- `GET /catalogo/{empresa_id}` (compatibilidad)
- `GET /barrios/search`
- `GET /cliente/buscar/{empresaID}/{identificacion}`

### Documentación interactiva

- Swagger UI: `http://127.0.0.1:8001/docs`
- ReDoc: `http://127.0.0.1:8001/redoc`

## 5) CORS

Configurado en `app/main.py` con estos orígenes:

- `http://127.0.0.1:5500`
- `http://localhost:5500`
- `http://127.0.0.1:5173`
- `http://localhost:5173`
- `http://127.0.0.1:3000`
- `http://localhost:3000`

Parámetros:

- `allow_credentials=True`
- `allow_methods=["*"]`
- `allow_headers=["*"]`

## 6) Endpoints disponibles

### Catálogo

- `GET /catalogo/empresa/{empresa_id}`
  - Retorna productos activos por empresa (`Producto.activo == 1`).

- `GET /catalogo/{empresa_id}`
  - Endpoint legado compatible (delegado al endpoint nuevo).

### Empresa (multiempresa)

- `GET /empresa/por-slug/{slug}`
  - Resuelve empresa por slug (`flora`, `petalops`, etc.).
  - Respuesta:

```json
{
  "empresaId": 3,
  "nombre": "Flora"
}
```

- `GET /empresa/por-dominio/{slug}`
  - Endpoint compatible que tambien resuelve por slug/subdominio.

- `PUT /empresa/{empresa_id}/slug`
  - Actualiza slug de empresa.
  - Errores:
  - `400` slug invalido
  - `404` empresa no encontrada
  - `409` slug ya existe

### Clientes

- `GET /cliente/buscar/{empresaID}/{identificacion}`
  - Busca cliente por empresa + identificación.

### Barrios

- `GET /barrios/search?q=...&empresa_id=...&sucursal_id=...`
  - Búsqueda de barrios (mínimo 2 caracteres), máximo 10 resultados.

### Pedidos

- `POST /pedido/checkout`
  - Flujo transaccional recomendado para checkout.

- `POST /pedido`
  - Flujo alterno de creación de pedido.

- `PUT /pedido/{pedido_id}/estado/{nuevo_estado_id}`
  - Cambia estado del pedido validando transición permitida.

### Pagos (Wompi)

- `POST /pagos/wompi/checkout-link`
  - Genera URL firmada de checkout para un `pedidoID` ya creado.

- `POST /pagos/wompi/confirmar`
  - Actualiza estado del pago por `referencia` y, si queda `APPROVED`, mueve el pedido a `PAGADO/APROBADO` si existe ese estado activo.

- `GET /pagos/wompi/status?referencia=...`
  - Consulta el estado registrado del pago.

- `GET /api/pagos/verificar?id=transactionId`
  - Consulta estado de una transaccion directamente en WOMPI.
  - Respuesta pensada para frontend:

```json
{
  "id": "txn_123",
  "status": "approved",
  "providerStatus": "APPROVED"
}
```

Valores posibles en `status`:
- `approved`
- `declined`
- `pending`

## 7) Ejemplo de checkout

### Request

```json
{
  "empresaID": 1,
  "sucursalID": 1,
  "productos": [
    { "productoID": 1, "cantidad": 2 },
    { "productoID": 2, "cantidad": 1 }
  ],
  "cliente": {
    "nombreCompleto": "Cliente Demo",
    "telefono": "3001234567",
    "email": "demo@correo.com"
  },
  "entrega": {
    "direccion": "Calle 123 #45-67",
    "barrioID": 10,
    "fechaEntrega": "2026-03-01T10:00:00",
    "mensaje": "Opcional"
  }
}
```

### Response

```json
{
  "pedidoID": 123,
  "total": 250000.0,
  "estado": "CREADO"
}
```

## 8) Reglas del checkout (`POST /pedido/checkout`)

1. Valida que `productos` no esté vacío.
2. Valida que cada `cantidad` sea mayor que 0.
3. Obtiene estado inicial activo con nombre `CREADO`.
4. Valida que todos los productos existan, estén activos y pertenezcan a la empresa.
5. Busca cliente por `empresaID + telefono`; si no existe, lo crea.
6. Crea pedido y detalles con precio tomado desde base de datos.
7. Calcula y actualiza totales (`totalBruto`, `totalIva`, `totalNeto`).
8. Crea registro de entrega.
9. Hace `commit` al final; ante error hace `rollback`.

## 9) Flujo recomendado con Wompi

1. Crear pedido con `POST /pedido/checkout`.
2. Generar link de pago con `POST /pagos/wompi/checkout-link` enviando el `pedidoID`.
3. Redirigir al usuario al `checkoutUrl` retornado.
4. Confirmar resultado con `POST /pagos/wompi/confirmar` (idealmente desde webhook/callback).

## 10) Notas

- El endpoint `/pedido/checkout` está desacoplado en `app/services/pedido_service.py`.
- No se usan precios enviados por frontend para totalizar pedidos.
- La integración Wompi usa firma SHA-256 con el patrón: `reference + amount-in-cents + currency + integrity_secret`.
- Ejecuta `sql/create_pago_table.sql` antes de usar los endpoints de pagos.
- Si la tabla `Pago` ya existe de una versión previa, ejecuta `sql/alter_pago_wompi_fields.sql`.

## 11) Scripts de migración (Excel)

- `migrations/validar_excel_floristeria.py`
  - Valida consistencia del Excel de Floristeria antes de migrar.

- `migrations/onboarding_empresa_excel.py`
  - Migra datos base de empresa (empresa, catalogo, clientes) desde Excel.
  - Soporta `--apply` y `dry-run` por defecto.

- `migrations/depurar_clientes_duplicados.py`
  - Detecta/elimina duplicados de clientes por `empresaID + identificacion`.

## 12) SQL de multiempresa

- `sql/alter_empresa_add_dominio.sql`
  - Agrega columna `dominio` e indice.

- `sql/alter_empresa_add_slug.sql`
  - Agrega columna `slug` e indice unico.

## 13) Quick Start Multiempresa (Frontend)

1. Resolver empresa por slug:

```http
GET /empresa/por-slug/{slug}
```

Ejemplo:

```http
GET /empresa/por-slug/flora
```

Respuesta:

```json
{
  "empresaId": 3,
  "nombre": "Flora"
}
```

2. Consumir catalogo con el `empresaId` retornado:

```http
GET /catalogo/empresa/3
```

3. Usar ese mismo `empresaId` en los endpoints transaccionales (cliente, pedido, pagos).
