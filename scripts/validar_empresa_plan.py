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

print('--- Empresa (id=3) ---')
cur.execute('SELECT * FROM petalops."Empresa" WHERE "idEmpresa" = 3')
print(cur.fetchall())

print('\n--- Plan (todos) ---')
cur.execute('SELECT * FROM petalops."Plan"')
print(cur.fetchall())

print('\n--- EmpresaPlan (si existe) ---')
try:
    cur.execute('SELECT * FROM petalops."EmpresaPlan" WHERE "empresaID" = 3')
    print(cur.fetchall())
except Exception as e:
    print('No existe tabla EmpresaPlan:', e)

cur.close()
conn.close()
