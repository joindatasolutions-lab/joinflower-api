import json
from pathlib import Path

from sqlalchemy import text

from app.database import SessionLocal, engine


FLORA_EMPRESA_ID = 3


def _safe_parse_json(raw_value):
    text_value = str(raw_value or "").strip()
    if not text_value:
        return {}
    try:
        parsed = json.loads(text_value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _extract_canal_flora(raw_respuesta):
    payload = _safe_parse_json(raw_respuesta)
    metadata = payload.get("_petalopsMetadata")
    if not isinstance(metadata, dict):
        return None
    value = str(metadata.get("canalFlora") or "").strip()
    return value or None


def main():
    db = SessionLocal()
    try:
        sql_path = Path(__file__).resolve().parents[1] / "sql" / "alter_flora_payment_phase2.sql"
        with sql_path.open("r", encoding="utf-8") as handle:
            raw_conn = engine.raw_connection()
            try:
                cursor = raw_conn.cursor()
                cursor.execute(handle.read())
                raw_conn.commit()
            finally:
                raw_conn.close()

        pagos = db.execute(
            text(
                """
                SELECT id_pago, pedido_id, metodo_pago, raw_respuesta
                FROM petalops.pago
                WHERE empresa_id = :empresa_id
                """
            ),
            {"empresa_id": FLORA_EMPRESA_ID},
        ).mappings().all()

        metodo_rows = db.execute(
            text(
                """
                SELECT id_metodo_pago, nombre
                FROM petalops.metodo_pago_catalogo
                WHERE empresa_id = :empresa_id
                """
            ),
            {"empresa_id": FLORA_EMPRESA_ID},
        ).mappings().all()
        metodo_by_name = {str(row["nombre"]).strip(): int(row["id_metodo_pago"]) for row in metodo_rows}

        canal_rows = db.execute(
            text(
                """
                SELECT id_canal_venta, nombre
                FROM petalops.canal_venta
                WHERE empresa_id = :empresa_id
                """
            ),
            {"empresa_id": FLORA_EMPRESA_ID},
        ).mappings().all()
        canal_by_name = {str(row["nombre"]).strip(): int(row["id_canal_venta"]) for row in canal_rows}

        inserted_payment_links = 0
        inserted_channels = 0

        for pago in pagos:
            pago_id = int(pago["id_pago"])
            pedido_id = int(pago["pedido_id"])
            methods = [part.strip() for part in str(pago["metodo_pago"] or "").split("|") if part.strip()]

            db.execute(
                text(
                    """
                    DELETE FROM petalops.pago_metodo
                    WHERE empresa_id = :empresa_id
                      AND pedido_id = :pedido_id
                    """
                ),
                {"empresa_id": FLORA_EMPRESA_ID, "pedido_id": pedido_id},
            )

            for index, method_name in enumerate(methods, start=1):
                metodo_id = metodo_by_name.get(method_name)
                if metodo_id is None:
                    continue
                db.execute(
                    text(
                        """
                        INSERT INTO petalops.pago_metodo (
                            empresa_id,
                            pago_id,
                            pedido_id,
                            metodo_pago_id,
                            orden,
                            created_at,
                            updated_at
                        )
                        VALUES (
                            :empresa_id,
                            :pago_id,
                            :pedido_id,
                            :metodo_pago_id,
                            :orden,
                            NOW(),
                            NOW()
                        )
                        ON CONFLICT DO NOTHING
                        """
                    ),
                    {
                        "empresa_id": FLORA_EMPRESA_ID,
                        "pago_id": pago_id,
                        "pedido_id": pedido_id,
                        "metodo_pago_id": metodo_id,
                        "orden": index,
                    },
                )
                inserted_payment_links += 1

            canal_name = _extract_canal_flora(pago["raw_respuesta"])
            canal_id = canal_by_name.get(canal_name) if canal_name else None

            db.execute(
                text(
                    """
                    DELETE FROM petalops.pedido_canal_venta
                    WHERE empresa_id = :empresa_id
                      AND pedido_id = :pedido_id
                    """
                ),
                {"empresa_id": FLORA_EMPRESA_ID, "pedido_id": pedido_id},
            )

            if canal_id is not None:
                db.execute(
                    text(
                        """
                        INSERT INTO petalops.pedido_canal_venta (
                            empresa_id,
                            pedido_id,
                            canal_venta_id,
                            created_at,
                            updated_at
                        )
                        VALUES (
                            :empresa_id,
                            :pedido_id,
                            :canal_venta_id,
                            NOW(),
                            NOW()
                        )
                        ON CONFLICT DO NOTHING
                        """
                    ),
                    {
                        "empresa_id": FLORA_EMPRESA_ID,
                        "pedido_id": pedido_id,
                        "canal_venta_id": canal_id,
                    },
                )
                inserted_channels += 1

        db.commit()
        print(
            {
                "status": "ok",
                "empresa_id": FLORA_EMPRESA_ID,
                "pagos_procesados": len(pagos),
                "payment_links_inserted": inserted_payment_links,
                "channels_inserted": inserted_channels,
            }
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
