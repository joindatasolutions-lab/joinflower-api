"""
Script para actualizar masivamente el campo codigoProducto de los productos de FLORA (empresa_id=3)
según el id de la hoja 'name' del Excel FLORA_APP_V2.xlsx.

- Solo actualiza productos cuyo nombre coincida exactamente (ignorando mayúsculas/minúsculas y espacios).
- El nuevo codigoProducto será FLR-3-{id} donde id es el de la hoja Excel.
"""


import sys
from pathlib import Path
import pandas as pd
from sqlalchemy.orm import Session

# Asegura que el directorio raíz esté en sys.path para importar 'app'
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import SessionLocal
from app.models.producto import Producto

EXCEL_PATH = "csv/empresas/flora/FLORA_APP_V2.xlsx"
EMPRESA_ID = 3

# Leer Excel y construir mapeo nombre normalizado -> id
excel = pd.ExcelFile(EXCEL_PATH)
sheet_name = None
for name in excel.sheet_names:
    if 'catalogo' in name.lower():
        sheet_name = name
        break
if not sheet_name:
    raise Exception('No se encontró hoja Catalogo en el Excel')
df = pd.read_excel(excel, sheet_name=sheet_name)

def normalize(text):
    return str(text).strip().lower() if pd.notna(text) else None

def get_id_entero(valor):
    try:
        return str(int(float(valor)))
    except Exception:
        return str(valor)

# Mapeo nombre normalizado -> id (solo parte entera), tomando siempre el primer id encontrado para cada nombre
name_to_id = {}
for _, row in df.iterrows():
    nombre_norm = normalize(row['name'])
    if pd.notna(row['name']) and pd.notna(row['id']) and nombre_norm not in name_to_id:
        name_to_id[nombre_norm] = get_id_entero(row['id'])

# Actualizar en base de datos
session: Session = SessionLocal()
try:
    productos = session.query(Producto).filter(Producto.empresaID == EMPRESA_ID).all()
    actualizados = 0
    for prod in productos:
        nombre_norm = normalize(prod.nombreProducto)
        if nombre_norm in name_to_id:
            nuevo_codigo = f"FLR-3-{name_to_id[nombre_norm]}"
            if prod.codigoProducto != nuevo_codigo:
                prod.codigoProducto = nuevo_codigo
                actualizados += 1
    session.commit()
    print(f"Productos actualizados con código de Excel: {actualizados}")
finally:
    session.close()
