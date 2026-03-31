import psycopg2

# Configuración PostgreSQL

conn = psycopg2.connect(
    host='136.119.27.100',
    user='joindata',
    password='Emprender2026#',
    dbname='joinflower-dev',
    port=5432
)
cur = conn.cursor()
cur.execute('SET search_path TO petalops')

# IDs de ejemplo (ajusta según tus datos reales)
empresa_id = 3
plan_id = 1
usuarios = [
    {'login': 'joinadmin', 'user_id': 1},
    {'login': 'flora.admin', 'user_id': 18},
    {'login': 'flora.pedidos', 'user_id': 19},
]
modulos = [
    'pedidos', 'produccion', 'domicilios', 'inventario', 'usuarios', 'reportes'
]

# Borra asignaciones previas
cur.execute('DELETE FROM petalops."UsuarioModulo" WHERE "userID" IN (%s, %s, %s)', tuple(u['user_id'] for u in usuarios))
cur.execute('DELETE FROM petalops."EmpresaModulo" WHERE "empresaID" = %s', (empresa_id,))
cur.execute('DELETE FROM petalops."PlanModulo" WHERE "planID" = %s', (plan_id,))

# Regenera PlanModulo
for modulo in modulos:
    cur.execute('INSERT INTO petalops."PlanModulo" ("planID", "modulo", "activo") VALUES (%s, %s, 1) ON CONFLICT DO NOTHING', (plan_id, modulo))
# Regenera EmpresaModulo
for modulo in modulos:
    cur.execute('INSERT INTO petalops."EmpresaModulo" ("empresaID", "modulo", "activo", "updatedAt") VALUES (%s, %s, 1, NOW()) ON CONFLICT DO NOTHING', (empresa_id, modulo))
# Regenera UsuarioModulo
for u in usuarios:
    for modulo in modulos:
        cur.execute('INSERT INTO petalops."UsuarioModulo" ("userID", "modulo", "activo", "updatedAt") VALUES (%s, %s, 1, NOW()) ON CONFLICT DO NOTHING', (u['user_id'], modulo))

conn.commit()
cur.close()
conn.close()
print('Asignaciones de módulos regeneradas para usuarios de test.')
