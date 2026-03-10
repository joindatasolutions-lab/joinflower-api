# PetalOps API (FastAPI)

Backend multi-tenant para gestion comercial y operativa de floristerias (catalogo, pedidos, produccion, domicilios, inventario y usuarios), construido con FastAPI + SQLAlchemy sobre MySQL.

## 1) Arquitectura y estructura

```text
app/
  core/
  models/
  routers/
  schemas/
  services/
  database.py
  main.py
sql/
scripts/
tests/
front/
docs/
```

- `app/models`: mapeo de tablas SQLAlchemy.
- `app/schemas`: contratos de entrada/salida (Pydantic).
- `app/services`: logica de negocio transaccional.
- `app/routers`: endpoints HTTP por dominio.
- `sql`: migraciones/alter idempotentes.
- `scripts`: seeds y utilidades operativas.
- `tests`: pruebas unitarias e integracion.

## 2) Requisitos

- Python 3.10+
- MySQL/MariaDB accesible
- Entorno virtual recomendado

## 3) Configuracion de entorno

El backend toma configuracion desde variables de entorno (o `.env`) leidas en `app/database.py`.

Ejemplo:

```env
DATABASE_HOST=127.0.0.1
DATABASE_PORT=3306
DATABASE_NAME=joinflower
DATABASE_USER=tu_usuario
DATABASE_PASSWORD=tu_password
JWT_SECRET_KEY=cambia-esta-clave
```

## 4) Instalacion y ejecucion

### Backend (API)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

Salud basica:

- `http://127.0.0.1:8001/ping`
- `http://127.0.0.1:8001/health`
- `http://127.0.0.1:8001/docs`

### Frontend rapido incluido en este repo

```powershell
python -m http.server 5500 -d front
```

Abrir: `http://127.0.0.1:5500`

### Frontend principal (Petalops React/Vite)

Si trabajas con el frontend completo en repositorio separado (`Petalops`):

```powershell
npm install
npm run dev -- --host 127.0.0.1 --port 5500
```

## 5) CORS local habilitado

En `app/main.py` estan permitidos origenes locales comunes:

- `http://127.0.0.1:5500`
- `http://localhost:5500`
- `http://127.0.0.1:5173`
- `http://localhost:5173`
- `http://127.0.0.1:3000`
- `http://localhost:3000`

## 6) Funcionalidades clave

### Pedidos con numeracion por sucursal

- `idPedido` permanece como llave tecnica interna.
- `numeroPedido` es consecutivo por `empresaID + sucursalID`.
- `codigoPedido` es el codigo visible para negocio (con prefijo de sucursal cuando aplica).
- La asignacion de consecutivo se hace de forma transaccional para evitar duplicados.

### Checkout transaccional

`POST /pedido/checkout` valida productos, cliente, entrega, estado inicial y totales, y persiste pedido + detalle + entrega en una sola transaccion.

### Auth y autorizacion multi-tenant

- Login JWT: `POST /auth/login`
- Perfil: `GET /auth/me`
- Claims base: `userID`, `empresaID`, `rolID`, `planID`.
- Enforcements:
- Aislamiento por empresa.
- Permisos por rol/modulo/accion.
- Restriccion por plan.
- Overrides por empresa y por usuario (`EmpresaModulo`, `UsuarioModulo`).

### Produccion inteligente por evento

- Al aprobar un pedido, crea/actualiza produccion.
- Autoasignacion solo para pendientes de hoy.
- Trigger manual: `POST /produccion/asignar-pendientes-hoy`.
- Sin polling permanente.

## 7) Migraciones SQL recomendadas

Ejecutar segun entorno (todas son idempotentes o preparadas para despliegue progresivo):

- `sql/alter_auth_multitenant.sql`
- `sql/alter_pedido_fecha_hora_fields.sql`
- `sql/alter_pedido_motivo_rechazo.sql`
- `sql/alter_domicilios_module.sql`
- `sql/alter_inventario_module.sql`
- `sql/alter_produccion_module.sql`
- `sql/alter_usuario_modulo_override.sql`
- `sql/alter_empresa_modulo_override.sql`
- `sql/alter_usuario_login_unique.sql`

Notas:

- Para datos demo base puedes usar `sql/seed_auth_example.sql` y `sql/seed_empresas_demo.sql`.
- Para semillas de usuarios de prueba por empresa, ver carpeta `scripts`.

## 8) Usuarios de prueba y credenciales

Se dejaron credenciales de trabajo en:

- `docs/credenciales_prueba/empresa3_flora.md`
- `docs/credenciales_prueba/empresa1_demo.md`

Scripts de seed asociados:

- `scripts/seed_flora_empresa3_users.py`
- `scripts/seed_empresa1_test_users.py`

## 9) Testing

### Ejecutar pruebas unitarias

```powershell
pytest -q
```

### Ejecutar integracion (si aplica en tu entorno)

```powershell
$env:RUN_INTEGRATION_TESTS="1"
pytest -m integration -q
```

Archivos de prueba relevantes:

- `tests/test_multitenant_guard_and_numero.py`
- `tests/test_tenant_table_guard.py`
- `tests/test_security_helpers.py`
- `tests/test_role_module_access_matrix.py`

Tambien hay workflow CI en `.github/workflows/ci-pytest.yml`.

## 10) E2E rapido sugerido

1. Levantar API en `8001`.
2. Hacer login con un usuario de `empresaID` conocida.
3. Crear pedido por `POST /pedido/checkout`.
4. Consultar `GET /pedidos` y validar que aparezcan `numeroPedido` y `codigoPedido`.

## 11) Endpoints de referencia

- `GET /catalogo/{empresa_id}`
- `GET /barrios/search`
- `GET /cliente/buscar/{empresaID}/{identificacion}`
- `POST /pedido/checkout`
- `GET /pedidos`
- `GET /entregas/pedido/{pedido_id}/mensaje`
- `GET /produccion`
- `GET /domicilios`
- `GET /inventario`
- `POST /auth/login`
- `GET /auth/me`

## 12) Consideraciones importantes

- El frontend no define permisos: backend siempre valida token, empresa y accion.
- Evitar exponer credenciales productivas en repositorio.
- Mantener migraciones SQL versionadas y ejecutadas por ambiente.
