"""
Script para migrar floristas desde la hoja 'Floristas' del Excel FLORA_APP_V2.xlsx a la tabla Florista.
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
from app.models.florista import Florista

EXCEL_PATH = "csv/empresas/flora/FLORA_APP_V2.xlsx"
EMPRESA_ID = 3
SUCURSAL_ID = 1  # Valor por defecto

# Leer Excel
excel = pd.ExcelFile(EXCEL_PATH)
df = pd.read_excel(excel, sheet_name="Floristas")

def map_estado(disponibilidad):
    if str(disponibilidad).strip().lower() in ["si", "sí"]:
        return "Activo", True
    return "Inactivo", False

session: Session = SessionLocal()
try:
    insertados = 0
    for _, row in df.iterrows():
        nombre = str(row["Nombre"]).strip()
        capacidad_diaria = int(row["CargaHoy"]) if not pd.isna(row["CargaHoy"]) else 0
        estado, activo = map_estado(row["Disponibilidad"])
        florista = Florista(
            empresaID=EMPRESA_ID,
            sucursalID=SUCURSAL_ID,
            nombre=nombre,
            capacidadDiaria=capacidad_diaria,
            trabajosSimultaneosPermitidos=1,
            estado=estado,
            activo=activo,
            especialidades=None,
            createdAt=datetime.now(),
            updatedAt=datetime.now(),
        )
        session.add(florista)
        insertados += 1
    session.commit()
    print(f"Floristas insertados: {insertados}")
finally:
    session.close()
