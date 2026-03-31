import os
from sqlalchemy import text
from app.database import SessionLocal


def test_db_runtime_debug():
    print("\n===== DATABASE RUNTIME DEBUG =====")

    print("DATABASE_URL ENV:", os.getenv("DATABASE_URL"))

    s = SessionLocal()

    db_name = s.execute(text("SELECT current_database()")).scalar()
    schema = s.execute(text("SELECT current_schema()")).scalar()
    search_path = s.execute(text("SHOW search_path")).scalar()

    print("DB NAME:", db_name)
    print("CURRENT SCHEMA:", schema)
    print("SEARCH PATH:", search_path)

    tables = s.execute(
        text("""
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_name = 'Usuario'
        """)
    ).fetchall()

    print("Usuario tables:", tables)

    users = s.execute(
        text("""
        SELECT login, "empresaID"
        FROM petalops."Usuario"
        ORDER BY login
        """)
    ).fetchall()

    print("Users found:", users)

    assert True