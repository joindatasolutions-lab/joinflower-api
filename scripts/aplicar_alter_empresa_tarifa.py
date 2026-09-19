from pathlib import Path
import sys

from dotenv import load_dotenv
from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from app.database import engine


SQL_PATH = ROOT / "sql" / "alter_empresa_tarifa.sql"


def main() -> None:
    sql = SQL_PATH.read_text(encoding="utf-8")
    with engine.begin() as conn:
        conn.execute(text(sql))
        tarifas = conn.execute(
            text(
                """
                SELECT id_empresa, tarifa
                FROM petalops.empresa
                ORDER BY id_empresa
                """
            )
        ).mappings().all()

    invalidas = [
        dict(row)
        for row in tarifas
        if int(row["tarifa"]) != (1500 if int(row["id_empresa"]) == 3 else 2500)
    ]
    if invalidas:
        raise RuntimeError(f"Se encontraron tarifas incorrectas: {invalidas}")

    print({"tarifas": [dict(row) for row in tarifas]})


if __name__ == "__main__":
    main()
