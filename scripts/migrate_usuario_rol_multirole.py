from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.database import SessionLocal


def main() -> None:
    db = SessionLocal()
    try:
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS petalops.usuario_rol (
                  usuario_id BIGINT NOT NULL,
                  rol_id BIGINT NOT NULL,
                  empresa_id BIGINT NOT NULL,
                  principal BOOLEAN NOT NULL DEFAULT FALSE,
                  activo BOOLEAN NOT NULL DEFAULT TRUE,
                  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  PRIMARY KEY (usuario_id, rol_id),
                  CONSTRAINT fk_usuario_rol_usuario FOREIGN KEY (usuario_id)
                    REFERENCES petalops.usuario(id_usuario),
                  CONSTRAINT fk_usuario_rol_rol FOREIGN KEY (rol_id)
                    REFERENCES petalops.rol(id_rol),
                  CONSTRAINT fk_usuario_rol_empresa FOREIGN KEY (empresa_id)
                    REFERENCES petalops.empresa(id_empresa)
                );
                """
            )
        )
        inserted = db.execute(
            text(
                """
                INSERT INTO petalops.usuario_rol (
                    usuario_id, rol_id, empresa_id, principal, activo, created_at, updated_at
                )
                SELECT u.id_usuario,
                       u.rolid,
                       u.empresa_id,
                       TRUE,
                       TRUE,
                       CURRENT_TIMESTAMP,
                       CURRENT_TIMESTAMP
                FROM petalops.usuario u
                JOIN petalops.rol r
                  ON r.id_rol = u.rolid
                 AND r.empresa_id = u.empresa_id
                WHERE u.id_usuario IS NOT NULL
                  AND u.rolid IS NOT NULL
                  AND u.empresa_id IS NOT NULL
                ON CONFLICT (usuario_id, rol_id) DO UPDATE SET
                    empresa_id = EXCLUDED.empresa_id,
                    principal = TRUE,
                    activo = TRUE,
                    updated_at = CURRENT_TIMESTAMP
                """
            )
        ).rowcount

        deactivated_extra_principals = db.execute(
            text(
                """
                UPDATE petalops.usuario_rol ur
                SET principal = FALSE,
                    updated_at = CURRENT_TIMESTAMP
                FROM petalops.usuario u
                WHERE ur.usuario_id = u.id_usuario
                  AND ur.rol_id <> u.rolid
                  AND ur.principal = TRUE
                """
            )
        ).rowcount

        db.execute(text("CREATE INDEX IF NOT EXISTS idx_usuario_rol_usuario_activo ON petalops.usuario_rol (usuario_id, activo);"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_usuario_rol_empresa_rol ON petalops.usuario_rol (empresa_id, rol_id);"))
        db.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_usuario_rol_principal ON petalops.usuario_rol (usuario_id) WHERE principal = TRUE AND activo = TRUE;"))

        total = db.execute(text("SELECT COUNT(*) FROM petalops.usuario_rol WHERE activo = TRUE")).scalar()
        db.commit()
        print(f"usuario_rol listo. upserted={inserted}; principales_extra_desactivados={deactivated_extra_principals}; activos={total}")
    except SQLAlchemyError:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
