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
- `GET /catalogo/{empresa_id}`
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

- `GET /catalogo/{empresa_id}`
  - Retorna productos activos por empresa.

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

## 9) Notas

- El endpoint `/pedido/checkout` está desacoplado en `app/services/pedido_service.py`.
- No se usan precios enviados por frontend para totalizar pedidos.
- La lógica de pago no está implementada en esta API.
