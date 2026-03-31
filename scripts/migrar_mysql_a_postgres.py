import os
import pymysql
import psycopg2
from psycopg2.extras import execute_values

# Configuración MySQL
MYSQL_CONFIG = {
    'host': '148.113.221.17',
    'user': 'joindata_joindata',
    'password': 'Emprender2025#',
    'database': 'joindata_app',
    'port': 3306,
    'cursorclass': pymysql.cursors.DictCursor
}



# Configuración PostgreSQL
POSTGRES_CONFIG = {
    'host': '136.119.27.100',
    'user': 'joindata',
    'password': 'Emprender2026#',
    'dbname': 'joinflower-dev',
    'port': 5432
}

# Orden de tablas según dependencias
TABLE_ORDER = [
    'Empresa',
    'Empresa',
    'Sucursal',
    'Rol',
    'EmpresaModulo',     # Asignación de módulos a empresa
    'UsuarioModulo',     # Asignación de módulos a usuario
    'PermisoModulo',     # Permisos de módulos
    'Usuario',
    'Cliente',
    'Categoria',
    'Producto',
    'Proveedor',  # Debe ir antes de Inventario
    'Insumo',     # Debe ir antes de Inventario por la FK insumoID
    'Inventario',
    'MovimientoInventario',  # Debe ir después de Inventario
    'EstadoPedido', # Debe ir antes de Pedido por la FK estadoPedidoID
    'Pedido',
    'PedidoDetalle',
    'Produccion',
    'Florista',
    'Domiciliario',
    'Empleado',
    'Barrio',
    'Entrega'
]

def fetch_mysql_table(table, mysql_conn):
    with mysql_conn.cursor() as cursor:
        cursor.execute(f"SELECT * FROM `{table}`;")
        return cursor.fetchall()

def insert_postgres_table(table, rows, pg_conn):
    if not rows:
        return
    columns = rows[0].keys()
    values = [[row[col] for col in columns] for row in rows]
    cols_str = ','.join(f'"{col}"' for col in columns)
    # Insertar en el esquema petalops
    sql = f'INSERT INTO petalops."{table}" ({cols_str}) VALUES %s ON CONFLICT DO NOTHING'
    with pg_conn.cursor() as cursor:
        execute_values(cursor, sql, values)
    pg_conn.commit()

def main():
    mysql_conn = pymysql.connect(**MYSQL_CONFIG)
    pg_conn = psycopg2.connect(**POSTGRES_CONFIG)
    for table in TABLE_ORDER:
        print(f'Transfiriendo {table}...')
        rows = fetch_mysql_table(table, mysql_conn)
        insert_postgres_table(table, rows, pg_conn)
        print(f'{table}: {len(rows)} filas migradas.')
    mysql_conn.close()
    pg_conn.close()

if __name__ == '__main__':
    main()
