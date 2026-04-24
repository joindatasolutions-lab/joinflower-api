from datetime import datetime, timezone

from sqlalchemy import text

from app.database import SessionLocal
from app.models.proveedor import Proveedor


SEED_PROVIDERS = [
    {"nombre": "Flores de la Sabana", "codigo": "PROV-FLO-001"},
    {"nombre": "Rosas Premium SAS", "codigo": "PROV-FLO-002"},
    {"nombre": "Empaques Botanicos", "codigo": "PROV-EMP-001"},
    {"nombre": "Cintas y Detalles", "codigo": "PROV-ACC-001"},
    {"nombre": "Insumos Florales Andinos", "codigo": "PROV-INS-001"},
]


def main() -> None:
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        created = 0
        updated = 0

        for entry in SEED_PROVIDERS:
            proveedor = (
                db.query(Proveedor)
                .filter(
                    (Proveedor.codigoProveedor == entry["codigo"])
                    | (Proveedor.nombreProveedor == entry["nombre"])
                )
                .first()
            )

            if proveedor:
                db.execute(
                    text(
                        """
                        UPDATE petalops.proveedor
                        SET nombre_proveedor = :nombre,
                            codigo_proveedor = :codigo,
                            activo = 1,
                            updated_at = :updated_at
                        WHERE id_proveedor = :id_proveedor
                        """
                    ),
                    {
                        "id_proveedor": int(proveedor.idProveedor),
                        "nombre": entry["nombre"],
                        "codigo": entry["codigo"],
                        "updated_at": now,
                    },
                )
                updated += 1
                continue

            db.execute(
                text(
                    """
                    INSERT INTO petalops.proveedor (
                        empresa_id,
                        nombre_proveedor,
                        codigo_proveedor,
                        activo,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        NULL,
                        :nombre,
                        :codigo,
                        1,
                        :created_at,
                        :updated_at
                    )
                    """
                ),
                {
                    "nombre": entry["nombre"],
                    "codigo": entry["codigo"],
                    "created_at": now,
                    "updated_at": now,
                },
            )
            created += 1

        db.commit()
        print({"status": "ok", "created": created, "updated": updated})
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
