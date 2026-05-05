import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.database import SessionLocal


pytestmark = pytest.mark.integration


def test_db_runtime_debug():
    if os.getenv("RUN_INTEGRATION_TESTS", "0") != "1":
        pytest.skip("Integration test skipped. Set RUN_INTEGRATION_TESTS=1 to execute.")

    print("\n===== DATABASE RUNTIME DEBUG =====")
    print("DATABASE_URL ENV:", os.getenv("DATABASE_URL"))

    s = SessionLocal()
    try:
        try:
            db_name = s.execute(text("SELECT current_database()")).scalar()
            schema = s.execute(text("SELECT current_schema()")).scalar()
            search_path = s.execute(text("SHOW search_path")).scalar()
        except OperationalError as exc:
            pytest.skip(f"Database not available for integration debug test: {exc}")

        print("DB NAME:", db_name)
        print("CURRENT SCHEMA:", schema)
        print("SEARCH PATH:", search_path)

        tables = s.execute(
            text(
                """
                SELECT table_schema, table_name
                FROM information_schema.tables
                WHERE table_name = 'Usuario'
                """
            )
        ).fetchall()

        print("Usuario tables:", tables)

        try:
            users = s.execute(
                text(
                    """
                    SELECT login, empresa_id
                    FROM petalops.usuario
                    ORDER BY login
                    """
                )
            ).fetchall()
        except ProgrammingError as exc:
            pytest.skip(f"Current schema does not expose expected auth table shape: {exc}")

        print("Users found:", users)
    finally:
        s.close()
