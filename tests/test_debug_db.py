import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.database import SessionLocal


pytestmark = pytest.mark.integration


def test_print_db_info():
    if os.getenv("RUN_INTEGRATION_TESTS", "0") != "1":
        pytest.skip("Integration test skipped. Set RUN_INTEGRATION_TESTS=1 to execute.")

    print("DATABASE_URL:", os.getenv("DATABASE_URL"))
    session = SessionLocal()
    try:
        try:
            users = session.execute(
                text("SELECT login, empresa_id, estado FROM petalops.usuario ORDER BY empresa_id NULLS FIRST, login")
            ).fetchall()
        except (OperationalError, ProgrammingError) as exc:
            pytest.skip(f"Database not available for integration debug test: {exc}")

        print("Usuarios en la base de datos:")
        for row in users:
            print(row)
    finally:
        session.close()
