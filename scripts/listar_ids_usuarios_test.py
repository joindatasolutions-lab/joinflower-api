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

# Consulta los IDs y logins de los usuarios de prueba
cur.execute('SELECT "idusuario", "login" FROM petalops."Usuario" WHERE "login" IN (%s, %s, %s)', ('joinadmin', 'flora.admin', 'flora.pedidos'))
usuarios = cur.fetchall()
for row in usuarios:
    print(f"login: {row[1]}, idusuario: {row[0]}")

cur.close()
conn.close()
