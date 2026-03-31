import psycopg2


conn = psycopg2.connect(
    host='136.119.27.100',
    user='joindata',
    password='Emprender2026#',
    dbname='joinflower-dev',
    port=5432
)
cur = conn.cursor()
cur.execute('SET search_path TO petalops')

usuarios = [
    {'login': 'joinadmin', 'user_id': 1},
    {'login': 'flora.admin', 'user_id': 18},
    {'login': 'flora.pedidos', 'user_id': 19},
]
empresa_id = 3
plan_id = 1

print('--- UsuarioModulo ---')
for u in usuarios:
    cur.execute('SELECT "modulo", "activo" FROM petalops."UsuarioModulo" WHERE "userID" = %s', (u['user_id'],))
    rows = cur.fetchall()
    print(f"{u['login']} (id={u['user_id']}): {rows}")

print('\n--- EmpresaModulo ---')
cur.execute('SELECT "modulo", "activo" FROM petalops."EmpresaModulo" WHERE "empresaID" = %s', (empresa_id,))
print(cur.fetchall())

print('\n--- PlanModulo ---')
cur.execute('SELECT "modulo", "activo" FROM petalops."PlanModulo" WHERE "planID" = %s', (plan_id,))
print(cur.fetchall())

cur.close()
conn.close()
