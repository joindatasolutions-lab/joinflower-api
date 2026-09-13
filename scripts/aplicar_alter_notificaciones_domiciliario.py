from pathlib import Path
import sys

from dotenv import load_dotenv
from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from app.database import engine


SQL_PATH = ROOT / "sql" / "alter_notificaciones_domiciliario.sql"


def main() -> None:
    sql = SQL_PATH.read_text(encoding="utf-8")
    with engine.begin() as conn:
        conn.execute(text(sql))
        columns = conn.execute(
            text(
                """
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = 'petalops'
                  AND (
                    (table_name = 'empresa_configuracion_asignacion'
                     AND column_name IN (
                       'notificacion_pedido_aceptado_activa',
                       'notificacion_pedido_entregado_activa',
                       'notificacion_nuevo_pedido_domiciliario_activa'
                     ))
                    OR (table_name = 'usuario' AND column_name = 'celular')
                    OR (table_name = 'whatsapp_notificacion' AND column_name = 'usuario_destino_id')
                  )
                ORDER BY table_name, column_name
                """
            )
        ).all()
    if len(columns) != 5:
        raise RuntimeError("La migracion termino sin crear todas las columnas esperadas")
    print("Migracion de notificaciones a domiciliarios aplicada y validada.")


if __name__ == "__main__":
    main()
