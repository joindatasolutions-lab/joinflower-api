import os

import pytest
from sqlalchemy import text

from app.database import SessionLocal


pytestmark = pytest.mark.integration

# Tablas globales o de configuracion que no requieren empresaID directo.
TABLES_ALLOWED_WITHOUT_EMPRESA_ID = {
    "Empresa",
    "EstadoPedido",
    "PermisoModulo",
    "PlanModulo",
    "UsuarioModulo",
}


def _integration_enabled() -> bool:
    return os.getenv("RUN_INTEGRATION_TESTS", "0") == "1"


def test_operational_tables_must_have_empresa_id_column():
    if not _integration_enabled():
        pytest.skip("Integration test skipped. Set RUN_INTEGRATION_TESTS=1 to execute.")

    s = SessionLocal()
    try:
        all_tables = {
            row[0]
            for row in s.execute(
                text(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'petalops'
                    """
                )
            ).fetchall()
        }

        tables_with_empresa = {
            row[0]
            for row in s.execute(
                text(
                                        """
                                        SELECT table_name
                                        FROM information_schema.columns
                                        WHERE table_catalog = current_database()
                                            AND column_name = 'empresaID'
                                        GROUP BY table_name
                                        """
                )
            ).fetchall()
        }

        missing = sorted(
            table
            for table in all_tables
            if table not in TABLES_ALLOWED_WITHOUT_EMPRESA_ID and table not in tables_with_empresa
        )

        assert not missing, (
            "Las siguientes tablas operativas no tienen empresaID y rompen aislamiento multi-tenant: "
            + ", ".join(missing)
        )
    finally:
        s.close()


def test_tables_with_empresa_id_must_not_have_nulls():
    if not _integration_enabled():
        pytest.skip("Integration test skipped. Set RUN_INTEGRATION_TESTS=1 to execute.")

    s = SessionLocal()
    try:
        tables_with_empresa = [
            row[0]
            for row in s.execute(
                text(
                    """
                    SELECT table_name
                    FROM information_schema.columns
                    WHERE table_catalog = current_database()
                        AND column_name = 'empresaID'
                    GROUP BY table_name
                    ORDER BY table_name
                    """
                )
            ).fetchall()
        ]

        offenders = []
        for table in tables_with_empresa:
            null_count = int(
                s.execute(text(f'SELECT COUNT(*) FROM petalops."{table}" WHERE "empresaID" IS NULL')).scalar() or 0
            )
            if null_count > 0:
                offenders.append((table, null_count))

        assert not offenders, (
            "Hay registros con empresaID NULL: "
            + ", ".join(f"{table}={count}" for table, count in offenders)
        )
    finally:
        s.close()
