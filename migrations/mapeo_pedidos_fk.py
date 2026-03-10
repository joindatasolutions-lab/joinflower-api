"""
Script para mapear identificaciones de clientes y estados de pedido desde la hoja 'Registros' del Excel FLORA_APP_V2.xlsx
para validar FK antes de migrar pedidos.
Genera dos reportes CSV: clientes_no_encontrados.csv y estados_no_encontrados.csv
"""

import sys
from pathlib import Path
import pandas as pd

# Asegura que el directorio raíz esté en sys.path para importar 'app'
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import SessionLocal
from app.models.cliente import Cliente
from app.models.estadopedido import EstadoPedido

EXCEL_PATH = "csv/empresas/flora/FLORA_APP_V2.xlsx"
EMPRESA_ID = 3

# Leer Excel
excel = pd.ExcelFile(EXCEL_PATH)
df = pd.read_excel(excel, sheet_name="Registros")

# Mapeo de clientes
session = SessionLocal()
try:
    # Cargar identificaciones de clientes existentes
    clientes = session.query(Cliente).filter(Cliente.empresaID == EMPRESA_ID).all()
    ident_to_id = {str(c.identificacion).strip(): c.idCliente for c in clientes}
    # Cargar estados de pedido existentes
    estados = session.query(EstadoPedido).all()
    estado_to_id = {str(e.nombreEstado).strip().lower(): e.idEstadoPedido for e in estados}
finally:
    session.close()

clientes_no_encontrados = []
estados_no_encontrados = []

for idx, row in df.iterrows():
    ident = str(row["Identificacion"]).strip()
    estado = str(row["Estado"]).strip().lower()
    if ident not in ident_to_id:
        clientes_no_encontrados.append({"fila_excel": idx+2, "identificacion": ident})
    if estado not in estado_to_id:
        estados_no_encontrados.append({"fila_excel": idx+2, "estado": row["Estado"]})

pd.DataFrame(clientes_no_encontrados).to_csv("migrations/reports/mapeo_pedidos_clientes_no_encontrados.csv", index=False, encoding="utf-8-sig")
pd.DataFrame(estados_no_encontrados).to_csv("migrations/reports/mapeo_pedidos_estados_no_encontrados.csv", index=False, encoding="utf-8-sig")

print(f"Clientes no encontrados: {len(clientes_no_encontrados)}")
print(f"Estados no encontrados: {len(estados_no_encontrados)}")
