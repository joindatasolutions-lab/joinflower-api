from __future__ import annotations
from sqlalchemy import text
from app.database import SessionLocal
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- Crear/actualizar joinadmin en empresa 1 ---
def ensure_joinadmin():
    session = SessionLocal()
    try:
        empresa_id = 1
        rol_row = session.execute(text('SELECT "idRol" FROM "petalops"."Rol" WHERE "empresaID" = :empresa_id AND "nombreRol" = :rol LIMIT 1'), {"empresa_id": empresa_id, "rol": "Admin"}).first()
        if not rol_row:
            session.execute(text('INSERT INTO "petalops"."Rol" ("empresaID", "nombreRol") VALUES (:empresa_id, :rol) ON CONFLICT ("empresaID", "nombreRol") DO NOTHING'), {"empresa_id": empresa_id, "rol": "Admin"})
            rol_row = session.execute(text('SELECT "idRol" FROM "petalops"."Rol" WHERE "empresaID" = :empresa_id AND "nombreRol" = :rol LIMIT 1'), {"empresa_id": empresa_id, "rol": "Admin"}).first()
        rol_id = int(rol_row[0])
        # Siempre usar el password exacto que esperan los tests
        password_hash = pwd_context.hash("Admin123*")
        # Intentar UPDATE primero
        result = session.execute(
            text(
                'UPDATE "petalops"."Usuario" SET "passwordHash" = :password_hash, "rolID" = :rol_id, "estado" = \'Activo\', "updatedAt" = CURRENT_TIMESTAMP '
                'WHERE "empresaID" = :empresa_id AND "login" = :login'
            ),
            {
                "empresa_id": empresa_id,
                "login": "joinadmin",
                "password_hash": password_hash,
                "rol_id": rol_id,
            },
        )
        if result.rowcount == 0:
            session.execute(
                text(
                    'INSERT INTO "petalops"."Usuario" ("empresaID", "sucursalID", "nombre", "login", "email", "passwordHash", "rolID", "estado", "createdAt", "updatedAt") '
                    'VALUES (:empresa_id, 1, :nombre, :login, :email, :password_hash, :rol_id, \'Activo\', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)'
                ),
                {
                    "empresa_id": empresa_id,
                    "nombre": "Admin Local",
                    "login": "joinadmin",
                    "email": "admin@empresa1.com",
                    "password_hash": password_hash,
                    "rol_id": rol_id,
                },
            )
        session.commit()
    finally:
        session.close()

def main():
    session = SessionLocal()
    try:
        conn = session
        ensure_empresa(conn)
        sucursal_id = ensure_sucursal(conn)
        role_ids = ensure_roles_and_permissions(conn)
        ensure_empresa_modules(conn)
        user_ids = upsert_users(conn, role_ids, sucursal_id)
        ensure_operational_people(conn, sucursal_id)
        session.commit()
        print("OK: seed Flora empresaID=3 aplicado")
        print("sucursalID:", sucursal_id)
        print("roles:")
        for role_name, rid in sorted(role_ids.items()):
            print(f"  - {role_name}: {rid}")
        print("users:")
        for login, uid in sorted(user_ids.items()):
            print(f"  - {login}: {uid}")
    except Exception:
        session.rollback()
        raise


from datetime import datetime, timezone

from passlib.context import CryptContext
from sqlalchemy import text

from app.database import SessionLocal

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

EMPRESA_ID = 3
EMPRESA_NOMBRE = "Flora"

ROLE_PERMS = {
    "Admin": {
        "pedidos": (1, 1, 1, 1),
        "produccion": (1, 1, 1, 1),
        "domicilios": (1, 1, 1, 1),
        "inventario": (1, 1, 1, 1),
        "reportes": (1, 1, 1, 1),
        "usuarios": (1, 1, 1, 1),
    },
    "PEDIDOS": {
        "pedidos": (1, 1, 1, 0),
    },
    "FLORISTA": {
        "produccion": (1, 0, 1, 0),
    },
    "DOMICILIARIO": {
        "domicilios": (1, 0, 1, 0),
    },
    "INVENTARIO": {
        "inventario": (1, 1, 1, 0),
    },
}

USERS = [
    {"nombre": "Flora Empresa Admin", "login": "flora.admin", "email": "flora.admin@empresa3.local", "password": "FloraAdmin2026*", "rol": "Admin", "modulos": ["pedidos", "produccion", "domicilios", "inventario", "reportes", "usuarios"]},
    {"nombre": "Flora Operador Pedidos", "login": "flora.pedidos", "email": "flora.pedidos@empresa3.local", "password": "FloraPedidos2026*", "rol": "PEDIDOS", "modulos": ["pedidos"]},
    {"nombre": "Flora Florista 1", "login": "flora.florista1", "email": "flora.florista1@empresa3.local", "password": "FloraFlorista12026*", "rol": "FLORISTA", "modulos": ["produccion"]},
    {"nombre": "Flora Florista 2", "login": "flora.florista2", "email": "flora.florista2@empresa3.local", "password": "FloraFlorista22026*", "rol": "FLORISTA", "modulos": ["produccion"]},
    {"nombre": "Flora Florista 3", "login": "flora.florista3", "email": "flora.florista3@empresa3.local", "password": "FloraFlorista32026*", "rol": "FLORISTA", "modulos": ["produccion"]},
    {"nombre": "Flora Florista 4", "login": "flora.florista4", "email": "flora.florista4@empresa3.local", "password": "FloraFlorista42026*", "rol": "FLORISTA", "modulos": ["produccion"]},
    {"nombre": "Flora Domiciliario 1", "login": "flora.domi1", "email": "flora.domi1@empresa3.local", "password": "FloraDomi12026*", "rol": "DOMICILIARIO", "modulos": ["domicilios"]},
    {"nombre": "Flora Domiciliario 2", "login": "flora.domi2", "email": "flora.domi2@empresa3.local", "password": "FloraDomi22026*", "rol": "DOMICILIARIO", "modulos": ["domicilios"]},
    {"nombre": "Flora Domiciliario 3", "login": "flora.domi3", "email": "flora.domi3@empresa3.local", "password": "FloraDomi32026*", "rol": "DOMICILIARIO", "modulos": ["domicilios"]},
    {"nombre": "Flora Inventarista", "login": "flora.inventario", "email": "flora.inventario@empresa3.local", "password": "FloraInventario2026*", "rol": "INVENTARIO", "modulos": ["inventario"]},
]


def ensure_empresa(conn):
    conn.execute(
        text(
            """
            UPDATE "petalops"."Empresa"
            SET "nombreComercial" = :nombre,
                "estado" = COALESCE("estado", 1)
            WHERE "idEmpresa" = :empresa_id
            """
        ),
        {"empresa_id": EMPRESA_ID, "nombre": EMPRESA_NOMBRE},
    )


def ensure_sucursal(conn) -> int:
    row = conn.execute(
        text(
            """
            SELECT "idSucursal"
            FROM "petalops"."Sucursal"
            WHERE "empresaID" = :empresa_id
            ORDER BY "idSucursal"
            LIMIT 1
            """
        ),
        {"empresa_id": EMPRESA_ID},
    ).first()

    if row:
        return int(row[0])

    next_id = int(conn.execute(text("SELECT COALESCE(MAX(\"idSucursal\"), 0) + 1 FROM \"petalops\".\"Sucursal\"" )).scalar() or 1)
    now = datetime.now(timezone.utc)

    conn.execute(
        text(
            """
            INSERT INTO "petalops"."Sucursal" ("idSucursal", "empresaID", "nombreSucursal", "prefijoPedido", "estado", "createdAt", "updatedAt")
            VALUES (:id_sucursal, :empresa_id, :nombre, :prefijo, 'Activo', :now, :now)
            """
        ),
        {
            "id_sucursal": next_id,
            "empresa_id": EMPRESA_ID,
            "nombre": "Flora Principal",
            "prefijo": "FLORA",
            "now": now,
        },
    )
    return next_id


def ensure_roles_and_permissions(conn) -> dict[str, int]:
    role_ids: dict[str, int] = {}

    for role_name, perms in ROLE_PERMS.items():
        conn.execute(
            text(
                """
                INSERT INTO "petalops"."Rol" ("empresaID", "nombreRol")
                VALUES (:empresa_id, :rol)
                ON CONFLICT ("empresaID", "nombreRol") DO UPDATE SET "nombreRol" = EXCLUDED."nombreRol"
                """
            ),
            {"empresa_id": EMPRESA_ID, "rol": role_name},
        )

        role_id = conn.execute(
            text(
                """
                SELECT "idRol"
                FROM "petalops"."Rol"
                WHERE "empresaID" = :empresa_id AND "nombreRol" = :rol
                LIMIT 1
                """
            ),
            {"empresa_id": EMPRESA_ID, "rol": role_name},
        ).scalar()
        role_ids[role_name] = int(role_id)

        conn.execute(text('DELETE FROM "petalops"."PermisoModulo" WHERE "rolID" = :rol_id'), {"rol_id": int(role_id)})
        for modulo, vals in perms.items():
            puede_ver, puede_crear, puede_editar, puede_eliminar = vals
            conn.execute(
                text(
                    """
                    INSERT INTO "petalops"."PermisoModulo" ("rolID", "modulo", "puedeVer", "puedeCrear", "puedeEditar", "puedeEliminar", "empresaID")
                    VALUES (:rol_id, :modulo, :v, :c, :e, :d, :empresa_id)
                    """
                ),
                {
                    "rol_id": int(role_id),
                    "modulo": modulo,
                    "v": int(bool(puede_ver)),
                    "c": int(bool(puede_crear)),
                    "e": int(bool(puede_editar)),
                    "d": int(bool(puede_eliminar)),
                    "empresa_id": EMPRESA_ID,
                },
            )

    return role_ids


def ensure_empresa_modules(conn):
    # Override de módulos activos a nivel empresa (sin afectar otras empresas).
    conn.execute(text('DELETE FROM "petalops"."EmpresaModulo" WHERE "empresaID" = :empresa_id'), {"empresa_id": EMPRESA_ID})
    for modulo in ["pedidos", "produccion", "domicilios", "inventario", "reportes", "usuarios"]:
        conn.execute(
            text(
                """
                INSERT INTO "petalops"."EmpresaModulo" ("empresaID", "modulo", "activo", "updatedAt")
                VALUES (:empresa_id, :modulo, 1, CURRENT_TIMESTAMP)
                """
            ),
            {"empresa_id": EMPRESA_ID, "modulo": modulo},
        )


def upsert_users(conn, role_ids: dict[str, int], sucursal_id: int):
    # Eliminar usuarios de test flora.* de la empresa antes de insertar
    logins = [user["login"].strip().lower() for user in USERS]
    conn.execute(
        text('DELETE FROM "petalops"."Usuario" WHERE "empresaID" = :empresa_id AND lower("login") = ANY(:logins)'),
        {"empresa_id": EMPRESA_ID, "logins": logins}
    )
    user_ids: dict[str, int] = {}

    for user in USERS:
        role_id = role_ids[user["rol"]]
        now = datetime.now(timezone.utc)
        login = user["login"].strip().lower()

        existing = conn.execute(
            text('SELECT "idusuario" FROM "petalops"."Usuario" WHERE "login" = :login LIMIT 1'),
            {"login": login},
        ).scalar()

        if existing:
            user_id = int(existing)
            conn.execute(
                text(
                    """
                    UPDATE "petalops"."Usuario"
                    SET "empresaID" = :empresa_id,
                        "sucursalID" = :sucursal_id,
                        "nombre" = :nombre,
                        "email" = :email,
                        "passwordHash" = :pwd_hash,
                        "rolID" = :rol_id,
                        "estado" = 'Activo',
                        "updatedAt" = :now,
                        "login" = :login
                    WHERE "idusuario" = :user_id
                    """
                ),
                {
                    "empresa_id": EMPRESA_ID,
                    "sucursal_id": sucursal_id,
                    "nombre": user["nombre"],
                    "email": user["email"],
                    "pwd_hash": pwd_context.hash(user["password"]),
                    "rol_id": role_id,
                    "now": now,
                    "user_id": user_id,
                    "login": login,
                },
            )
        else:
            conn.execute(
                text(
                    """
                    INSERT INTO "petalops"."Usuario" ("empresaID", "sucursalID", "nombre", "login", "email", "passwordHash", "rolID", "estado", "createdAt", "updatedAt")
                    VALUES (:empresa_id, :sucursal_id, :nombre, :login, :email, :pwd_hash, :rol_id, 'Activo', :now, :now)
                    """
                ),
                {
                    "empresa_id": EMPRESA_ID,
                    "sucursal_id": sucursal_id,
                    "nombre": user["nombre"],
                    "login": login,
                    "email": user["email"],
                    "pwd_hash": pwd_context.hash(user["password"]),
                    "rol_id": role_id,
                    "now": now,
                },
            )
            user_id = int(
                conn.execute(
                    text('SELECT "idusuario" FROM "petalops"."Usuario" WHERE "login" = :login LIMIT 1'),
                    {"login": login},
                ).scalar()
            )
        # Restricción por módulo a nivel usuario para respetar aislamiento de funcionalidades.
        conn.execute(text('DELETE FROM "petalops"."UsuarioModulo" WHERE "userID" = :uid'), {"uid": user_id})
        for modulo in user["modulos"]:
            conn.execute(
                text(
                    """
                    INSERT INTO "petalops"."UsuarioModulo" ("userID", "modulo", "activo", "updatedAt")
                    VALUES (:uid, :modulo, 1, :now)
                    """
                ),
                {"uid": user_id, "modulo": modulo, "now": now},
            )
        user_ids[login] = user_id
    return user_ids


def ensure_operational_people(conn, sucursal_id: int):
    # Ajustar el sequence de idFlorista para evitar claves duplicadas (si existe)
    seq_val = conn.execute(
        text('SELECT COALESCE(MAX("idFlorista"), 0) FROM "petalops"."Florista"')
    ).scalar()
    florista_seq_exists = conn.execute(
        text("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.sequences
                WHERE sequence_schema = 'petalops' AND sequence_name = 'Florista_idFlorista_seq'
            )
        """
    )).scalar()
    if florista_seq_exists:
        conn.execute(
            text('SELECT setval(\'"petalops"."Florista_idFlorista_seq"\', :seq_val)'),
            {"seq_val": seq_val if seq_val else 1}
        )

    # Ajustar el sequence de idDomiciliario para evitar claves duplicadas (si existe)
    seq_val_dom = conn.execute(
        text('SELECT COALESCE(MAX("idDomiciliario"), 0) FROM "petalops"."Domiciliario"')
    ).scalar()
    domi_seq_exists = conn.execute(
        text("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.sequences
                WHERE sequence_schema = 'petalops' AND sequence_name = 'Domiciliario_idDomiciliario_seq'
            )
        """
    )).scalar()
    if domi_seq_exists:
        conn.execute(
            text('SELECT setval(\'"petalops"."Domiciliario_idDomiciliario_seq"\', :seq_val)'),
            {"seq_val": seq_val_dom if seq_val_dom else 1}
        )

    for idx in range(1, 5):
        nombre = f"Flora Florista {idx}"
        now = datetime.now(timezone.utc)
        row = conn.execute(
            text(
                """
                SELECT "idFlorista"
                FROM "petalops"."Florista"
                WHERE "empresaID" = :empresa_id
                  AND "sucursalID" = :sucursal_id
                  AND "nombre" = :nombre
                LIMIT 1
                """
            ),
            {"empresa_id": EMPRESA_ID, "sucursal_id": sucursal_id, "nombre": nombre},
        ).first()
        if row:
            conn.execute(
                text(
                    """
                    UPDATE "petalops"."Florista"
                    SET "capacidadDiaria" = 12,
                        "trabajosSimultaneosPermitidos" = 2,
                        "estado" = 'Activo',
                        "activo" = 1,
                        "especialidades" = 'Ramos, arreglos',
                        "updatedAt" = :now
                    WHERE "idFlorista" = :id_florista
                    """
                ),
                {"id_florista": row[0], "now": now},
            )
        else:
            conn.execute(
                text(
                    """
                    INSERT INTO "petalops"."Florista" (
                        "empresaID", "sucursalID", "nombre", "capacidadDiaria", "trabajosSimultaneosPermitidos",
                        "estado", "activo", "especialidades", "createdAt", "updatedAt"
                    ) VALUES (
                        :empresa_id, :sucursal_id, :nombre, 12, 2,
                        'Activo', 1, 'Ramos, arreglos', :now, :now
                    )
                    """
                ),
                {"empresa_id": EMPRESA_ID, "sucursal_id": sucursal_id, "nombre": nombre, "now": now},
            )

    for idx in range(1, 4):
        nombre = f"Flora Domiciliario {idx}"
        telefono = f"31000000{idx}"
        now = datetime.now(timezone.utc)
        row = conn.execute(
            text(
                """
                SELECT "idDomiciliario"
                FROM "petalops"."Domiciliario"
                WHERE "empresaID" = :empresa_id
                  AND "sucursalID" = :sucursal_id
                  AND "nombre" = :nombre
                LIMIT 1
                """
            ),
            {"empresa_id": EMPRESA_ID, "sucursal_id": sucursal_id, "nombre": nombre},
        ).first()
        if row:
            conn.execute(
                text(
                    """
                    UPDATE "petalops"."Domiciliario"
                    SET "telefono" = :telefono,
                        "activo" = 1,
                        "updatedAt" = :now
                    WHERE "idDomiciliario" = :id_domiciliario
                    """
                ),
                {"id_domiciliario": row[0], "telefono": telefono, "now": now},
            )
        else:
            conn.execute(
                text(
                    """
                    INSERT INTO "petalops"."Domiciliario" (
                        "empresaID", "sucursalID", "nombre", "telefono", "activo", "createdAt", "updatedAt"
                    ) VALUES (
                        :empresa_id, :sucursal_id, :nombre, :telefono, 1, :now, :now
                    )
                    """
                ),
                {
                    "empresa_id": EMPRESA_ID,
                    "sucursal_id": sucursal_id,
                    "nombre": nombre,
                    "telefono": telefono,
                    "now": now,
                },
            )




if __name__ == "__main__":
    ensure_joinadmin()
    main()
