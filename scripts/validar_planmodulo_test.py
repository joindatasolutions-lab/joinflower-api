import psycopg2

# Configuración de conexión

conn = psycopg2.connect(
    host='136.119.27.100',
    user='joindata',
    password='Emprender2026#',
    dbname='joinflower-dev',
    port=5432
)
cur = conn.cursor()
cur.execute('SET search_path TO petalops')

# 1. Verificar empresa de prueba (empresaID=3)
cur.execute('SELECT "idEmpresa", "planID" FROM petalops."Empresa" WHERE "idEmpresa"=3')
empresa = cur.fetchone()
if empresa:
    print(f"Empresa 3: idEmpresa={empresa[0]}, planID={empresa[1]}")
else:
    print("Empresa 3 no encontrada.")

# 2. Verificar módulos activos para ese plan
plan_id = empresa[1] if empresa else 1
cur.execute('SELECT "modulo", "activo" FROM petalops."PlanModulo" WHERE "planID"=%s', (plan_id,))
modulos = cur.fetchall()
print(f"Módulos activos para planID={plan_id}:")
for modulo, activo in modulos:
    print(f"  {modulo}: {'Activo' if activo else 'Inactivo'}")

# 3. Validar que los módulos requeridos por los tests estén activos
requeridos = {"pedidos", "produccion", "domicilios", "inventario", "reportes", "usuarios"}
activos = {m.lower() for m, a in modulos if a}
print("\nMódulos requeridos presentes:")
for req in requeridos:
    print(f"  {req}: {'OK' if req in activos else 'FALTA'}")

cur.close()
conn.close()
