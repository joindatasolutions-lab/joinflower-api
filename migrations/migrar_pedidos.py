"""
Script para migrar pedidos válidos desde la hoja 'Registros' del Excel FLORA_APP_V2.xlsx a la tabla Pedido.
Solo inserta pedidos con cliente y estado válidos. Genera reporte de omitidos.
"""

import sys
from pathlib import Path
import pandas as pd
from datetime import datetime
from sqlalchemy.orm import Session

# Asegura que el directorio raíz esté en sys.path para importar 'app'
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import SessionLocal
from app.models.pedido import Pedido
from app.models.cliente import Cliente
from app.models.estadopedido import EstadoPedido

EXCEL_PATH = "csv/empresas/flora/FLORA_APP_V2.xlsx"
EMPRESA_ID = 3
SUCURSAL_ID = 1  # Valor por defecto

# Leer Excel
excel = pd.ExcelFile(EXCEL_PATH)
df = pd.read_excel(excel, sheet_name="Registros")

session: Session = SessionLocal()
try:
    # Cargar clientes y estados
    clientes = session.query(Cliente).filter(Cliente.empresaID == EMPRESA_ID).all()
    ident_to_id = {str(c.identificacion).strip(): c.idCliente for c in clientes}
    estados = session.query(EstadoPedido).all()
    estado_to_id = {str(e.nombreEstado).strip().lower(): e.idEstadoPedido for e in estados}

    insertados = 0
    omitidos = []
    for idx, row in df.iterrows():
        ident = str(row["Identificacion"]).strip()
        estado = str(row["Estado"]).strip().lower()
        pedido_num = row["Pedido"]
        if pd.isna(pedido_num):
            omitidos.append({"fila_excel": idx+2, "identificacion": ident, "estado": row["Estado"], "motivo": "Sin número de pedido"})
            continue
        if ident not in ident_to_id or estado not in estado_to_id:
            omitidos.append({"fila_excel": idx+2, "identificacion": ident, "estado": row["Estado"], "motivo": "FK inválida"})
            continue

        def safe_float(val):
            if pd.isna(val):
                return 0.0
            try:
                return float(val)
            except Exception:
                return 0.0

        pedido = Pedido(
            empresaID=EMPRESA_ID,
            sucursalID=SUCURSAL_ID,
            clienteID=ident_to_id[ident],
            fechaPedido=pd.to_datetime(row["Fecha"]),
            estadoPedidoID=estado_to_id[estado],
            totalBruto=safe_float(row["Precio"]),
            totalIva=safe_float(row["Iva"]),
            totalNeto=safe_float(row["Total"]),
            numeroPedido=int(pedido_num),
            codigoPedido=str(int(pedido_num)),
            createdAt=datetime.now(),
            updatedAt=datetime.now(),
            version=1
        )
        session.add(pedido)
        insertados += 1
    session.commit()
    print(f"Pedidos insertados: {insertados}")
    pd.DataFrame(omitidos).to_csv("migrations/reports/pedidos_omitidos_por_fk.csv", index=False, encoding="utf-8-sig")
finally:
    session.close()
