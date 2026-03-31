import os
from app.database import SessionLocal
from sqlalchemy import text

def test_print_db_info():
    print('DATABASE_URL:', os.getenv('DATABASE_URL'))
    session = SessionLocal()
    users = session.execute(
        text('SELECT "login", "empresaID", "estado" FROM petalops."Usuario" ORDER BY "empresaID", "login"')
    ).fetchall()
    print('Usuarios en la base de datos:')
    for row in users:
        print(row)
    session.close()
