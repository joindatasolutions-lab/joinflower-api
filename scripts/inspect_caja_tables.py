import os
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv
from sqlalchemy import create_engine, text


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
load_dotenv(ROOT.parent / ".env")


def build_url() -> str:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        return database_url

    host = os.getenv("DATABASE_HOST") or os.getenv("DB_HOST")
    port = os.getenv("DATABASE_PORT") or os.getenv("DB_PORT") or "5432"
    name = os.getenv("DATABASE_NAME") or os.getenv("DB_NAME")
    user = os.getenv("DATABASE_USER") or os.getenv("DB_USER")
    password = quote_plus(os.getenv("DATABASE_PASSWORD") or os.getenv("DB_PASSWORD") or "")

    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}"


def main() -> None:
    engine = create_engine(
        build_url(),
        connect_args={"options": "-csearch_path=petalops"},
        pool_pre_ping=True,
    )

    table_query = text(
        """
        SELECT table_name, table_type
        FROM information_schema.tables
        WHERE table_schema = 'petalops'
          AND table_name ILIKE :pattern
        ORDER BY table_name
        """
    )
    column_query = text(
        """
        SELECT table_name, column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = 'petalops'
          AND table_name ILIKE :pattern
        ORDER BY table_name, ordinal_position
        """
    )
    key_query = text(
        """
        SELECT
            tc.table_name,
            tc.constraint_type,
            tc.constraint_name,
            string_agg(kcu.column_name, ', ' ORDER BY kcu.ordinal_position) AS columns,
            ccu.table_name AS referenced_table,
            string_agg(ccu.column_name, ', ' ORDER BY kcu.ordinal_position) AS referenced_columns
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        LEFT JOIN information_schema.constraint_column_usage ccu
          ON ccu.constraint_name = tc.constraint_name
         AND ccu.table_schema = tc.table_schema
        WHERE tc.table_schema = 'petalops'
          AND tc.table_name ILIKE :pattern
        GROUP BY
            tc.table_name,
            tc.constraint_type,
            tc.constraint_name,
            ccu.table_name
        ORDER BY tc.table_name, tc.constraint_type, tc.constraint_name
        """
    )
    view_query = text(
        """
        SELECT pg_get_viewdef('petalops.vw_caja_totales_diario'::regclass, true)
        """
    )

    with engine.connect() as conn:
        print("SCHEMA:", conn.execute(text("SELECT current_schema()")).scalar())

        print("\nCOUNTS")
        for table_name in ("caja",):
            count = conn.execute(text(f"SELECT count(*) FROM petalops.{table_name}")).scalar()
            print(f"{table_name}: {count}")

        print("\nTABLES")
        for row in conn.execute(table_query, {"pattern": "%caja%"}):
            print(f"{row.table_name} | {row.table_type}")

        print("\nCOLUMNS")
        for row in conn.execute(column_query, {"pattern": "%caja%"}):
            default = row.column_default or ""
            print(
                f"{row.table_name}.{row.column_name} | "
                f"{row.data_type} | nullable={row.is_nullable} | default={default}"
            )

        print("\nKEYS")
        for row in conn.execute(key_query, {"pattern": "%caja%"}):
            ref = ""
            if row.referenced_table and row.referenced_columns:
                ref = f" -> {row.referenced_table}({row.referenced_columns})"
            print(
                f"{row.table_name}({row.columns}) | "
                f"{row.constraint_type} | {row.constraint_name}{ref}"
            )

        if conn.execute(text("SELECT to_regclass('petalops.vw_caja_totales_diario') IS NOT NULL")).scalar():
            print("\nVIEW vw_caja_totales_diario")
            print(conn.execute(view_query).scalar())


if __name__ == "__main__":
    main()
