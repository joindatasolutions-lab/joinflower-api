from __future__ import annotations

from datetime import datetime, timezone

from passlib.context import CryptContext
from sqlalchemy import text

from app.database import SessionLocal

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

EMPRESA_ID = 1
EMPRESA_NOMBRE = "Empresa Prueba"

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
    {
        "nombre": "Demo Empresa Admin",
        "login": "demo1.admin",
        "email": "demo1.admin@empresa1.local",
        "password": "Demo1Admin2026*",
        "rol": "Admin",
        "modulos": ["pedidos", "produccion", "domicilios", "inventario", "reportes", "usuarios"],
    },
    {
        "nombre": "Demo Operador Pedidos",
        "login": "demo1.pedidos",
        "email": "demo1.pedidos@empresa1.local",
        "password": "Demo1Pedidos2026*",
        "rol": "PEDIDOS",
        "modulos": ["pedidos"],
    },
    {
        "nombre": "Demo Florista 1",
        "login": "demo1.florista1",
        "email": "demo1.florista1@empresa1.local",
        "password": "Demo1Florista12026*",
        "rol": "FLORISTA",
        "modulos": ["produccion"],
    },
    {
        "nombre": "Demo Florista 2",
        "login": "demo1.florista2",
        "email": "demo1.florista2@empresa1.local",
        "password": "Demo1Florista22026*",
        "rol": "FLORISTA",
        "modulos": ["produccion"],
    },
    {
        "nombre": "Demo Florista 3",
        "login": "demo1.florista3",
        "email": "demo1.florista3@empresa1.local",
        "password": "Demo1Florista32026*",
        "rol": "FLORISTA",
        "modulos": ["produccion"],
    },
    {
        "nombre": "Demo Florista 4",
        "login": "demo1.florista4",
        "email": "demo1.florista4@empresa1.local",
        "password": "Demo1Florista42026*",
        "rol": "FLORISTA",
        "modulos": ["produccion"],
    },
    {
        "nombre": "Demo Domiciliario 1",
        "login": "demo1.domi1",
        "email": "demo1.domi1@empresa1.local",
        "password": "Demo1Domi12026*",
        "rol": "DOMICILIARIO",
        "modulos": ["domicilios"],
    },
    {
        "nombre": "Demo Domiciliario 2",
        "login": "demo1.domi2",
        "email": "demo1.domi2@empresa1.local",
        "password": "Demo1Domi22026*",
        "rol": "DOMICILIARIO",
        "modulos": ["domicilios"],
    },
    {
        "nombre": "Demo Domiciliario 3",
        "login": "demo1.domi3",
        "email": "demo1.domi3@empresa1.local",
        "password": "Demo1Domi32026*",
        "rol": "DOMICILIARIO",
        "modulos": ["domicilios"],
    },
    {
        "nombre": "Demo Inventarista",
        "login": "demo1.inventario",
        "email": "demo1.inventario@empresa1.local",
        "password": "Demo1Inventario2026*",
        "rol": "INVENTARIO",
        "modulos": ["inventario"],
    },
]


def ensure_empresa(conn):
    conn.execute(
        text(
            """
            UPDATE Empresa
            SET nombreComercial = :nombre,
                estado = 1
            WHERE idEmpresa = :empresa_id
            """
        ),
        {"empresa_id": EMPRESA_ID, "nombre": EMPRESA_NOMBRE},
    )


def ensure_sucursal(conn) -> int:
    row = conn.execute(
        text(
            """
            SELECT idSucursal
            FROM Sucursal
            WHERE empresaID = :empresa_id
            ORDER BY idSucursal
            LIMIT 1
            """
        ),
        {"empresa_id": EMPRESA_ID},
    ).first()
    if row:
        return int(row[0])

    next_id = int(conn.execute(text("SELECT COALESCE(MAX(idSucursal), 0) + 1 FROM Sucursal")).scalar() or 1)
    now = datetime.now(timezone.utc)
    conn.execute(
        text(
            """
            INSERT INTO Sucursal (idSucursal, empresaID, nombreSucursal, prefijoPedido, estado, createdAt, updatedAt)
            VALUES (:id_sucursal, :empresa_id, :nombre, :prefijo, 'Activo', :now, :now)
            """
        ),
        {
            "id_sucursal": next_id,
            "empresa_id": EMPRESA_ID,
            "nombre": "Demo Principal",
            "prefijo": "DEMO1",
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
                INSERT INTO Rol (empresaID, nombreRol)
                VALUES (:empresa_id, :rol)
                ON DUPLICATE KEY UPDATE nombreRol = VALUES(nombreRol)
                """
            ),
            {"empresa_id": EMPRESA_ID, "rol": role_name},
        )

        role_id = conn.execute(
            text(
                """
                SELECT idRol
                FROM Rol
                WHERE empresaID = :empresa_id AND nombreRol = :rol
                LIMIT 1
                """
            ),
            {"empresa_id": EMPRESA_ID, "rol": role_name},
        ).scalar()
        role_ids[role_name] = int(role_id)

        conn.execute(text("DELETE FROM PermisoModulo WHERE rolID = :rol_id"), {"rol_id": int(role_id)})
        for modulo, vals in perms.items():
            v, c, e, d = vals
            conn.execute(
                text(
                    """
                    INSERT INTO PermisoModulo (rolID, modulo, puedeVer, puedeCrear, puedeEditar, puedeEliminar)
                    VALUES (:rol_id, :modulo, :v, :c, :e, :d)
                    """
                ),
                {
                    "rol_id": int(role_id),
                    "modulo": modulo,
                    "v": int(bool(v)),
                    "c": int(bool(c)),
                    "e": int(bool(e)),
                    "d": int(bool(d)),
                },
            )

    return role_ids


def ensure_empresa_modules(conn):
    conn.execute(text("DELETE FROM EmpresaModulo WHERE empresaID = :empresa_id"), {"empresa_id": EMPRESA_ID})
    for modulo in ["pedidos", "produccion", "domicilios", "inventario", "reportes", "usuarios"]:
        conn.execute(
            text(
                """
                INSERT INTO EmpresaModulo (empresaID, modulo, activo, updatedAt)
                VALUES (:empresa_id, :modulo, 1, NOW())
                """
            ),
            {"empresa_id": EMPRESA_ID, "modulo": modulo},
        )


def upsert_users(conn, role_ids: dict[str, int], sucursal_id: int):
    user_ids: dict[str, int] = {}
    for user in USERS:
        role_id = role_ids[user["rol"]]
        now = datetime.now(timezone.utc)
        existing = conn.execute(text("SELECT idUsuario FROM Usuario WHERE login = :login LIMIT 1"), {"login": user["login"]}).scalar()

        if existing:
            user_id = int(existing)
            conn.execute(
                text(
                    """
                    UPDATE Usuario
                    SET empresaID = :empresa_id,
                        sucursalID = :sucursal_id,
                        nombre = :nombre,
                        email = :email,
                        passwordHash = :pwd_hash,
                        rolID = :rol_id,
                        estado = 'Activo',
                        updatedAt = :now
                    WHERE idUsuario = :user_id
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
                },
            )
        else:
            conn.execute(
                text(
                    """
                    INSERT INTO Usuario (empresaID, sucursalID, nombre, login, email, passwordHash, rolID, estado, createdAt, updatedAt)
                    VALUES (:empresa_id, :sucursal_id, :nombre, :login, :email, :pwd_hash, :rol_id, 'Activo', :now, :now)
                    """
                ),
                {
                    "empresa_id": EMPRESA_ID,
                    "sucursal_id": sucursal_id,
                    "nombre": user["nombre"],
                    "login": user["login"],
                    "email": user["email"],
                    "pwd_hash": pwd_context.hash(user["password"]),
                    "rol_id": role_id,
                    "now": now,
                },
            )
            user_id = int(conn.execute(text("SELECT idUsuario FROM Usuario WHERE login = :login LIMIT 1"), {"login": user["login"]}).scalar())

        conn.execute(text("DELETE FROM UsuarioModulo WHERE userID = :uid"), {"uid": user_id})
        for modulo in user["modulos"]:
            conn.execute(
                text(
                    """
                    INSERT INTO UsuarioModulo (userID, modulo, activo, updatedAt)
                    VALUES (:uid, :modulo, 1, :now)
                    """
                ),
                {"uid": user_id, "modulo": modulo, "now": now},
            )

        user_ids[user["login"]] = user_id

    return user_ids


def ensure_operational_people(conn, sucursal_id: int):
    for idx in range(1, 5):
        nombre = f"Demo Florista {idx}"
        exists = conn.execute(
            text(
                """
                SELECT idFlorista
                FROM Florista
                WHERE empresaID = :empresa_id AND sucursalID = :sucursal_id AND nombre = :nombre
                LIMIT 1
                """
            ),
            {"empresa_id": EMPRESA_ID, "sucursal_id": sucursal_id, "nombre": nombre},
        ).scalar()
        if not exists:
            now = datetime.now(timezone.utc)
            conn.execute(
                text(
                    """
                    INSERT INTO Florista (
                      empresaID, sucursalID, nombre, capacidadDiaria, trabajosSimultaneosPermitidos,
                      estado, activo, especialidades, createdAt, updatedAt
                    ) VALUES (
                      :empresa_id, :sucursal_id, :nombre, 10, 2,
                      'Activo', 1, 'Ramos', :now, :now
                    )
                    """
                ),
                {"empresa_id": EMPRESA_ID, "sucursal_id": sucursal_id, "nombre": nombre, "now": now},
            )

    for idx in range(1, 4):
        nombre = f"Demo Domiciliario {idx}"
        telefono = f"32000000{idx}"
        exists = conn.execute(
            text(
                """
                SELECT idDomiciliario
                FROM Domiciliario
                WHERE empresaID = :empresa_id AND sucursalID = :sucursal_id AND nombre = :nombre
                LIMIT 1
                """
            ),
            {"empresa_id": EMPRESA_ID, "sucursal_id": sucursal_id, "nombre": nombre},
        ).scalar()
        if not exists:
            now = datetime.now(timezone.utc)
            conn.execute(
                text(
                    """
                    INSERT INTO Domiciliario (empresaID, sucursalID, nombre, telefono, activo, createdAt, updatedAt)
                    VALUES (:empresa_id, :sucursal_id, :nombre, :telefono, 1, :now, :now)
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

        print("OK: seed empresaID=1 aplicado")
        print("sucursalID:", sucursal_id)
        print("users:")
        for login, uid in sorted(user_ids.items()):
            print(f"  - {login}: {uid}")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
