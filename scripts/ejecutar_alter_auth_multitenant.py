import psycopg2
import os

pg_config = {
    "host": os.getenv("PGHOST", "136.119.27.100"),
    "user": os.getenv("PGUSER", "joindata"),
    "password": os.getenv("PGPASSWORD", "Emprender2026#"),
    "dbname": os.getenv("PGDATABASE", "joinflower-dev"),
    "port": int(os.getenv("PGPORT", "5432")),
}

SQL_FILE = os.path.join(os.path.dirname(__file__), "..", "sql", "alter_auth_multitenant.sql")

with open(SQL_FILE, encoding="utf-8") as f:
    sql = f.read()

conn = psycopg2.connect(**pg_config)
conn.autocommit = True
cur = conn.cursor()

try:
    cur.execute("SET search_path TO petalops;")
    cur.execute(sql)
    print("Script alter_auth_multitenant.sql ejecutado correctamente.")
except Exception as e:
    print(f"Error ejecutando el script: {e}")
finally:
    cur.close()
    conn.close()
