import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal


def main() -> int:
    with SessionLocal() as db:
        print("PETALOPS_MODULE")
        for row in db.execute(
            text(
                """
                SELECT empresa_id, modulo, activo
                FROM petalops.empresa_modulo
                WHERE empresa_id = 2
                  AND modulo = 'notificaciones_whatsapp'
                """
            )
        ):
            print(dict(row._mapping))

        print("STATUS_COUNTS")
        for row in db.execute(
            text(
                """
                SELECT empresa_id, status, COUNT(*) AS count
                FROM petalops.whatsapp_notificacion
                GROUP BY empresa_id, status
                ORDER BY empresa_id, status
                """
            )
        ):
            print(dict(row._mapping))

        print("RECENT_DELIVERED_PETALOPS")
        for row in db.execute(
            text(
                """
                SELECT p.id_pedido, p.numero_pedido, e.id_entrega, e.estadoentregaid,
                       wn.id_notificacion, wn.status, wn.created_at AS notif_created_at
                FROM petalops.pedido p
                JOIN petalops.entrega e
                  ON e.pedido_id = p.id_pedido
                 AND e.empresa_id = p.empresa_id
                LEFT JOIN petalops.whatsapp_notificacion wn
                  ON wn.empresa_id = p.empresa_id
                 AND wn.pedido_id = p.id_pedido
                 AND wn.evento = 'ORDER_DELIVERED'
                 AND wn.canal = 'WHATSAPP'
                WHERE p.empresa_id = 2
                  AND e.estadoentregaid = 4
                ORDER BY e.id_entrega DESC
                LIMIT 10
                """
            )
        ):
            print(dict(row._mapping))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
