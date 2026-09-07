import os
from pathlib import Path

import psycopg2


BASE_DIR = Path(__file__).resolve().parents[1]
SQL_FILE = BASE_DIR / "sql" / "alter_whatsapp_notificacion_webhook_indexes.sql"


def main() -> int:
    pg_config = {
        "host": os.getenv("PGHOST") or os.getenv("DATABASE_HOST", "136.119.27.100"),
        "user": os.getenv("PGUSER") or os.getenv("DATABASE_USER", "joindata"),
        "password": os.getenv("PGPASSWORD") or os.getenv("DATABASE_PASSWORD"),
        "dbname": os.getenv("PGDATABASE") or os.getenv("DATABASE_NAME", "joinflower-dev"),
        "port": int(os.getenv("PGPORT") or os.getenv("DATABASE_PORT", "5432")),
        "sslmode": os.getenv("PGSSLMODE", "require"),
    }
    if not pg_config["password"]:
        raise RuntimeError("Falta PGPASSWORD o DATABASE_PASSWORD para conectar a la base de datos.")

    sql = SQL_FILE.read_text(encoding="utf-8")

    conn = psycopg2.connect(**pg_config)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'petalops'
                  AND tablename = 'whatsapp_notificacion'
                  AND indexname = 'idx_whatsapp_notificacion_meta_message_id'
                """
            )
            row = cur.fetchone()
            print("Indice verificado:", row[0] if row else "NO_ENCONTRADO")
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
