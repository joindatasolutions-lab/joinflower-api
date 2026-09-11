from pathlib import Path
import sys

from dotenv import load_dotenv
from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")
load_dotenv(Path("C:/Users/CAA4746/Documents/JOIN/Arquitectura/joinflower-api/.env"))

from app.database import engine

SQL_PATH = ROOT / "sql" / "alter_empresa_datos_transferencia_catalogo.sql"


def main() -> None:
    sql = SQL_PATH.read_text(encoding="utf-8")
    with engine.begin() as conn:
        conn.execute(text(sql))
        row = conn.execute(
            text(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN datos_transferencia_catalogo_activo THEN 1 ELSE 0 END) AS activos
                FROM petalops.empresa
                """
            )
        ).mappings().first()
    print(
        {
            "total_empresas": int(row["total"] or 0),
            "activos": int(row["activos"] or 0),
        }
    )


if __name__ == "__main__":
    main()
