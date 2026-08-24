# Guia — como conectarse a GCP en este proyecto y validar como Claude lo hace

Instrucciones para que otro agente (u otra sesion) pueda replicar el acceso a GCP/Cloud Run/Cloud SQL usado en esta sesion, y consultar costos por su cuenta.

## 1. Identidad y proyecto

- Cuenta gcloud ya autenticada en esta maquina: `joindatasolutions@gmail.com`
- Proyecto: `flora-471805`
- Config activa: `gcloud config list` (perfil `default`)

Verificar con:
```bash
gcloud config list
gcloud auth list --format="value(account,status)"
```

Si no esta autenticado: `gcloud auth login` (abre navegador) — no correrlo sin avisar al usuario, es una accion que cambia la sesion activa de gcloud en la maquina.

## 2. Recursos relevantes de este proyecto

| Recurso | Valor |
|---|---|
| Cloud Run service (backend) | `join-flower`, region `us-central1` |
| Cloud SQL instance | `joindata` (connection name `flora-471805:us-central1:joindata`), IP publica `136.119.27.100` |
| Nombre real de la BD de produccion | `joinflower-dev` (nombre historico, es la BD real que usa produccion — no es un ambiente de pruebas) |
| Usuario BD | `joindata` |
| Billing account | `015332-E5ADBF-49F589` |

## 3. Consultar logs de Cloud Run (seguro, solo lectura)

```bash
gcloud logging read '
resource.type="cloud_run_revision"
resource.labels.service_name="join-flower"
severity>=WARNING
timestamp>="2026-08-11T00:00:00Z"
' --limit=100 --format="value(timestamp,severity,httpRequest.status,httpRequest.requestUrl)" --project=flora-471805
```

Para ver logs con mas detalle usar `--format=json` redirigido a un archivo (nunca a la consola directa si el volumen es alto), y despues grep sobre el archivo.

## 4. Consultar variables de entorno de Cloud Run — REGLA DE SEGURIDAD

**Nunca imprimir el valor de variables secretas** (`DB_PASSWORD`, `JWT_SECRET`, `TEXMEBOT_API_KEY`, etc.) en la salida visible. Dos veces en esta sesion se filtraron por accidente usando un `--format` sin filtrar por nombre — ambas veces se recomendo rotar el secreto despues.

Correcto (solo nombres, seguro):
```bash
gcloud run services describe join-flower --region=us-central1 --project=flora-471805 \
  --format="value(spec.template.spec.containers[0].env[].name)"
```

Correcto (un valor NO secreto especifico, ej. DB_NAME):
```bash
gcloud run services describe join-flower --region=us-central1 --project=flora-471805 --format=json > archivo_local.json
grep -A1 '"name": "DB_NAME"' archivo_local.json
```

Incorrecto (NUNCA hacer esto — imprime todos los valores incluyendo secretos):
```bash
gcloud run services describe join-flower --format="value(spec.template.spec.containers[0].env)"
```

## 5. Consultar la base de datos de produccion directamente (solo lectura, con cuidado)

Cloud Run se conecta via socket unix (`INSTANCE_CONNECTION_NAME`), pero desde una maquina local se puede usar la IP publica si esta autorizada en el firewall de Cloud SQL.

### 5.1 Ver que redes estan autorizadas ahora
```bash
gcloud sql instances describe joindata --project=flora-471805 \
  --format="value(settings.ipConfiguration.authorizedNetworks[].value)"
```

### 5.2 Ver tu IP de salida actual
```bash
curl -s https://api.ipify.org
```

### 5.3 Si tu IP no esta autorizada: agregarla temporalmente (requiere confirmar con el usuario antes — es un cambio de firewall en produccion)

`--authorized-networks` REEMPLAZA toda la lista, hay que incluir las existentes + la nueva:
```bash
gcloud sql instances patch joindata --project=flora-471805 --quiet \
  --authorized-networks=<ip1>,<ip2>,<ip3>,<ip4>,<TU_IP_NUEVA>
```

**Inmediatamente despues de terminar la consulta, quitarla** (volver a la lista original sin tu IP):
```bash
gcloud sql instances patch joindata --project=flora-471805 --quiet \
  --authorized-networks=<ip1>,<ip2>,<ip3>,<ip4>
```

### 5.4 Credenciales de conexion (ya existen en un .env local, no hay que pedirlas)

Hay un `.env` en `c:/Users/CAA4746/Documents/JOIN/Arquitectura/joinflower-api/.env` con:
```
DATABASE_HOST=136.119.27.100
DATABASE_PORT=5432
DATABASE_NAME=joinflower-dev
DATABASE_USER=joindata
DATABASE_PASSWORD=<esta en el archivo, no imprimirla nunca en la salida>
```

### 5.5 Como conectar sin exponer la contrasena en la salida del comando

Todo en UNA sola linea de bash (el estado de shell no persiste entre invocaciones separadas de la tool):
```bash
export DBPASS=$(grep '^DATABASE_PASSWORD=' "c:/Users/CAA4746/Documents/JOIN/Arquitectura/joinflower-api/.env" | cut -d= -f2-)
export DBHOST=136.119.27.100 DBNAME=joinflower-dev DBUSER=joindata
python script.py   # el script lee os.environ, nunca debe hacer print() de la password
```

`psycopg2` ya esta instalado en el Python de este equipo (`C:\Users\CAA4746\AppData\Local\Programs\Python\Python311\python.exe`). Ejemplo de script minimo:
```python
import os, psycopg2, psycopg2.extras
conn = psycopg2.connect(
    host=os.environ["DBHOST"], port=5432, dbname=os.environ["DBNAME"],
    user=os.environ["DBUSER"], password=os.environ["DBPASS"],
    sslmode="require", connect_timeout=10,
)
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cur.execute("SELECT ...")  # SOLO SELECT salvo que el usuario haya confirmado explicitamente un UPDATE puntual
for row in cur.fetchall():
    print(dict(row))
```

**Cualquier UPDATE/DELETE sobre esta base de datos requiere confirmacion explicita del usuario antes de ejecutarlo**, mostrando el SQL exacto — esta sesion nunca escribio en produccion sin ese paso.

## 6. Costos de GCP — como consultarlos (esto quedo pendiente, no resuelto)

No existe un comando `gcloud billing costs` directo. Opciones reales:

1. **Consola web de Facturacion** (la mas simple, no requiere nada tecnico): https://console.cloud.google.com/billing → seleccionar la cuenta `015332-E5ADBF-49F589` → "Informes". Ahi se ve el desglose por servicio/mes visualmente. Esto lo tiene que abrir el usuario o alguien con acceso a la consola, un agente de terminal no puede navegar ahi.

2. **BigQuery Billing Export** (para consultarlo por comando/API): hay que verificar primero si ya esta configurada la exportacion de facturacion a BigQuery para esta cuenta (Facturacion → Exportaciones de facturacion en la consola). Si existe, se puede consultar con `bq query` o la libreria de Python de BigQuery. **En esta sesion `bq` fallo** porque pide un runtime `python3.14` que no esta instalado en esta maquina — para que otro agente lo intente, primero resolver eso (instalar el intérprete que pide `bq`, o usar la libreria `google-cloud-bigquery` de Python directamente en vez del CLI `bq`).

3. **Cloud Billing API "Cost Management"** (`cloudbilling.googleapis.com`) no expone gasto real historico facil por API sin la exportacion a BigQuery de por medio — en la practica, la via 2 (BigQuery) es la que usan la mayoria de integraciones automatizadas.

Verificado en esta sesion (sin secretos):
```bash
gcloud billing projects describe flora-471805 --format="value(billingAccountName,billingEnabled)"
# -> billingAccounts/015332-E5ADBF-49F589, True
```

## 7. Reglas generales que se siguieron toda la sesion (para que el otro agente se comporte igual)

- Nunca `git push --force`, nunca `rebase -i`, nunca commits sin que el usuario pida explicitamente commitear.
- Cada fix de codigo en un branch nuevo propio, PR por separado, nunca mergeado por el agente — el usuario revisa y mergea.
- Antes de cualquier cambio en infraestructura de produccion (Cloud SQL, Cloud Run, firewall) o escritura en la base de datos: explicar el plan exacto y esperar confirmacion explicita.
- Cambios de firewall/redes autorizadas: siempre revertir inmediatamente despues de usarlos.
- Nunca imprimir secretos (contrasenas, JWT secret, API keys) en la salida visible de ningun comando.
