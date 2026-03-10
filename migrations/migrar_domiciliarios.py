"""
Script para migrar domiciliarios desde la hoja 'Domiciliarios' del Excel FLORA_APP_V2.xlsx a la tabla Empleado.
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
from app.models.empleado import Empleado

EXCEL_PATH = "csv/empresas/flora/FLORA_APP_V2.xlsx"
EMPRESA_ID = 3
SUCURSAL_ID = 1  # Valor por defecto

# Leer Excel
excel = pd.ExcelFile(EXCEL_PATH)
df = pd.read_excel(excel, sheet_name="Domiciliarios")

def map_activo(disponibilidad):
    return str(disponibilidad).strip().lower() in ["si", "sí"]

def map_rol(externo):
    return "Domiciliario Externo" if str(externo).strip().lower() == "si" else "Domiciliario"

session: Session = SessionLocal()
try:
    insertados = 0
    for _, row in df.iterrows():
        nombre = str(row["Nombre"]).strip()
        activo = map_activo(row["Disponibilidad"])
        rol = map_rol(row["Externo"])
        empleado = Empleado(
            empresaID=EMPRESA_ID,
            sucursalID=SUCURSAL_ID,
            nombreEmpleado=nombre,
            rol=rol,
            activo=activo,
            createdAt=datetime.now(),
            updatedAt=datetime.now(),
        )
        session.add(empleado)
        insertados += 1
    session.commit()
    print(f"Domiciliarios insertados: {insertados}")
finally:
    session.close()
