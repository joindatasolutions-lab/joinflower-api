from __future__ import annotations

from pathlib import Path

from passlib.context import CryptContext
from sqlalchemy.exc import OperationalError
from sqlalchemy import create_engine, text

from app.database import DATABASE_URL

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

BASE_DIR = Path(__file__).resolve().parents[1]
SQL_MIGRATION = BASE_DIR / "sql" / "alter_auth_multitenant.sql"
SQL_DOMICILIOS_MIGRATION = BASE_DIR / "sql" / "alter_domicilios_module.sql"
SQL_LOGIN_MIGRATION = BASE_DIR / "sql" / "alter_usuario_login_unique.sql"
SQL_USUARIO_SUCURSAL_MIGRATION = BASE_DIR / "sql" / "alter_usuario_sucursal.sql"
SQL_USUARIO_AUDITORIA_MIGRATION = BASE_DIR / "sql" / "alter_usuario_auditoria.sql"
SQL_EMPRESA_MODULO_OVERRIDE_MIGRATION = BASE_DIR / "sql" / "alter_empresa_modulo_override.sql"
SQL_USUARIO_MODULO_OVERRIDE_MIGRATION = BASE_DIR / "sql" / "alter_usuario_modulo_override.sql"
SQL_INVENTARIO_MODULE_MIGRATION = BASE_DIR / "sql" / "alter_inventario_module.sql"

ADMIN_EMAIL = "admin@empresa1.com"
ADMIN_LOGIN = "joinadmin"
ADMIN_PASSWORD = "Admin123*"
ADMIN_NAME = "Admin Local"

DEFAULT_ROLE_MODULE_POLICY = {
    "Admin": {
        "pedidos": (1, 1, 1, 1),
        "produccion": (1, 1, 1, 1),
        "domicilios": (1, 1, 1, 1),
        "catalogo": (1, 1, 1, 1),
        "usuarios": (1, 1, 1, 1),
        "inventario": (1, 1, 1, 1),
    },
    "Florista": {
        "produccion": (1, 1, 1, 0),
        "catalogo": (1, 0, 0, 0),
    },
    "Pedidos": {
        "pedidos": (1, 1, 1, 0),
        "catalogo": (1, 0, 0, 0),
    },
    "Domiciliario": {
        "domicilios": (1, 1, 1, 0),
    },
    "Inventarista": {
        "catalogo": (1, 1, 1, 0),
        "inventario": (1, 1, 1, 0),
    },
    "Operativo": {
        "pedidos": (1, 1, 0, 0),
        "produccion": (1, 1, 0, 0),
        "inventario": (1, 0, 0, 0),
    },
}


def split_sql_statements(sql_text: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    in_string = False
    string_char = ""

    for ch in sql_text:
        if ch in ("'", '"'):
            if not in_string:
                in_string = True
                string_char = ch
            elif string_char == ch:
                in_string = False
                string_char = ""

        if ch == ";" and not in_string:
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
            continue

        current.append(ch)

    tail = "".join(current).strip()
    if tail:
        statements.append(tail)

    return statements


def run_migration(conn):
    sql_text = SQL_MIGRATION.read_text(encoding="utf-8")
    for stmt in split_sql_statements(sql_text):
        try:
            conn.execute(text(stmt))
        except OperationalError as exc:
            # Allow rerunning this initializer on partially migrated databases.
            mysql_code = getattr(getattr(exc, "orig", None), "args", [None])[0]
            if mysql_code in {1050, 1060, 1061}:  # table exists, duplicate column/index
                continue
            raise


def ensure_inventario_schema(conn):
    inventory_exists = conn.execute(
        text(
            """
            SELECT COUNT(*)
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'Inventario'
            """
        )
    ).scalar()
    if not int(inventory_exists or 0):
        return

    current_columns = {
        str(row[0])
        for row in conn.execute(
            text(
                """
                SELECT COLUMN_NAME
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'Inventario'
                """
            )
        ).all()
    }

    required_columns = [
        ("codigo", "VARCHAR(80) NOT NULL DEFAULT ''"),
        ("nombre", "VARCHAR(180) NOT NULL DEFAULT ''"),
        ("categoria", "VARCHAR(80) NOT NULL DEFAULT 'General'"),
        ("subcategoria", "VARCHAR(80) NULL"),
        ("color", "VARCHAR(80) NULL"),
        ("descripcion", "VARCHAR(255) NULL"),
        ("proveedorID", "BIGINT NULL"),
        ("codigoProveedor", "VARCHAR(80) NULL"),
        ("stockMinimo", "DECIMAL(12,2) NOT NULL DEFAULT 0"),
        ("valorUnitario", "DECIMAL(12,2) NOT NULL DEFAULT 0"),
        ("activo", "TINYINT(1) NOT NULL DEFAULT 1"),
        ("fechaUltimaActualizacion", "DATETIME NULL"),
    ]

    for column_name, ddl in required_columns:
        if column_name in current_columns:
            continue
        conn.execute(text(f"ALTER TABLE Inventario ADD COLUMN {column_name} {ddl}"))

    index_rows = conn.execute(text("SHOW INDEX FROM Inventario")).all()
    index_names = {str(row[2]) for row in index_rows if len(row) > 2 and row[2]}

    if "idx_inventario_empresa_categoria" not in index_names:
        conn.execute(text("CREATE INDEX idx_inventario_empresa_categoria ON Inventario (empresaID, categoria)"))
    if "idx_inventario_empresa_activo" not in index_names:
        conn.execute(text("CREATE INDEX idx_inventario_empresa_activo ON Inventario (empresaID, activo)"))
    if "idx_inventario_empresa_stock" not in index_names:
        conn.execute(text("CREATE INDEX idx_inventario_empresa_stock ON Inventario (empresaID, stockActual, stockMinimo)"))


def ensure_admin(conn):
    empresa_id_row = conn.execute(text("SELECT idEmpresa FROM Empresa ORDER BY idEmpresa ASC LIMIT 1")).first()
    if not empresa_id_row:
        raise RuntimeError("No existe ninguna empresa en la tabla Empresa")

    empresa_id = int(empresa_id_row[0])

    # Set minimal company auth context for login gating.
    conn.execute(
        text(
            """
            UPDATE Empresa
            SET estado = 'Activo', planID = COALESCE(planID, :plan_id), nombreComercial = COALESCE(nombreComercial, 'Empresa Demo')
            WHERE idEmpresa = :empresa_id
            """
        ),
        {"empresa_id": empresa_id, "plan_id": 1},
    )

    # Plan modules for basic operations.
    plan_modules = ["pedidos", "produccion", "domicilios", "catalogo", "inventario"]
    for modulo in plan_modules:
        conn.execute(
            text(
                """
                INSERT INTO PlanModulo (planID, modulo, activo)
                VALUES (:plan_id, :modulo, 1)
                ON DUPLICATE KEY UPDATE activo = VALUES(activo)
                """
            ),
            {"plan_id": 1, "modulo": modulo},
        )

    rol_id = None
    for role_name, module_policy in DEFAULT_ROLE_MODULE_POLICY.items():
        conn.execute(
            text(
                """
                INSERT INTO Rol (empresaID, nombreRol)
                VALUES (:empresa_id, :nombre)
                ON DUPLICATE KEY UPDATE nombreRol = VALUES(nombreRol)
                """
            ),
            {"empresa_id": empresa_id, "nombre": role_name},
        )

        role_row = conn.execute(
            text("SELECT idRol FROM Rol WHERE empresaID = :empresa_id AND nombreRol = :nombre LIMIT 1"),
            {"empresa_id": empresa_id, "nombre": role_name},
        ).first()
        if not role_row:
            continue

        current_role_id = int(role_row[0])
        if role_name == "Admin":
            rol_id = current_role_id

        for modulo, perms in module_policy.items():
            puede_ver, puede_crear, puede_editar, puede_eliminar = perms
            conn.execute(
                text(
                    """
                    INSERT INTO PermisoModulo (rolID, modulo, puedeVer, puedeCrear, puedeEditar, puedeEliminar)
                    VALUES (:rol_id, :modulo, :puede_ver, :puede_crear, :puede_editar, :puede_eliminar)
                    ON DUPLICATE KEY UPDATE
                      puedeVer = VALUES(puedeVer),
                      puedeCrear = VALUES(puedeCrear),
                      puedeEditar = VALUES(puedeEditar),
                      puedeEliminar = VALUES(puedeEliminar)
                    """
                ),
                {
                    "rol_id": current_role_id,
                    "modulo": modulo,
                    "puede_ver": int(bool(puede_ver)),
                    "puede_crear": int(bool(puede_crear)),
                    "puede_editar": int(bool(puede_editar)),
                    "puede_eliminar": int(bool(puede_eliminar)),
                },
            )

    if rol_id is None:
        raise RuntimeError("No fue posible obtener el rol Admin")

    password_hash = pwd_context.hash(ADMIN_PASSWORD)

    conn.execute(
        text(
            """
                        INSERT INTO Usuario (empresaID, sucursalID, nombre, login, email, passwordHash, rolID, estado, createdAt, updatedAt)
                        VALUES (:empresa_id, :sucursal_id, :nombre, :login, :email, :password_hash, :rol_id, 'Activo', NOW(), NOW())
            ON DUPLICATE KEY UPDATE
                            sucursalID = VALUES(sucursalID),
                            login = VALUES(login),
              nombre = VALUES(nombre),
              passwordHash = VALUES(passwordHash),
              rolID = VALUES(rolID),
              estado = 'Activo',
              updatedAt = NOW()
            """
        ),
        {
            "empresa_id": empresa_id,
            "sucursal_id": 1,
            "nombre": ADMIN_NAME,
            "login": ADMIN_LOGIN,
            "email": ADMIN_EMAIL,
            "password_hash": password_hash,
            "rol_id": rol_id,
        },
    )

    return empresa_id, rol_id


def main():
    engine = create_engine(DATABASE_URL, future=True)
    with engine.begin() as conn:
        run_migration(conn)
        if SQL_DOMICILIOS_MIGRATION.exists():
            sql_text = SQL_DOMICILIOS_MIGRATION.read_text(encoding="utf-8")
            for stmt in split_sql_statements(sql_text):
                try:
                    conn.execute(text(stmt))
                except OperationalError as exc:
                    mysql_code = getattr(getattr(exc, "orig", None), "args", [None])[0]
                    if mysql_code in {1005, 1050, 1060, 1061, 1062, 1826}:  # existing fk/table/column/index/key/constraint
                        continue
                    raise
        if SQL_LOGIN_MIGRATION.exists():
            sql_text = SQL_LOGIN_MIGRATION.read_text(encoding="utf-8")
            for stmt in split_sql_statements(sql_text):
                try:
                    conn.execute(text(stmt))
                except OperationalError as exc:
                    mysql_code = getattr(getattr(exc, "orig", None), "args", [None])[0]
                    if mysql_code in {1050, 1060, 1061, 1062, 1091}:  # existing table/column/index/dup/unknown drop
                        continue
                    raise
        if SQL_USUARIO_SUCURSAL_MIGRATION.exists():
            sql_text = SQL_USUARIO_SUCURSAL_MIGRATION.read_text(encoding="utf-8")
            for stmt in split_sql_statements(sql_text):
                try:
                    conn.execute(text(stmt))
                except OperationalError as exc:
                    mysql_code = getattr(getattr(exc, "orig", None), "args", [None])[0]
                    if mysql_code in {1050, 1060, 1061, 1062, 1091}:  # existing table/column/index/dup/unknown drop
                        continue
                    raise
        if SQL_USUARIO_AUDITORIA_MIGRATION.exists():
            sql_text = SQL_USUARIO_AUDITORIA_MIGRATION.read_text(encoding="utf-8")
            for stmt in split_sql_statements(sql_text):
                try:
                    conn.execute(text(stmt))
                except OperationalError as exc:
                    mysql_code = getattr(getattr(exc, "orig", None), "args", [None])[0]
                    if mysql_code in {1050, 1060, 1061, 1062, 1091}:  # existing table/column/index/dup/unknown drop
                        continue
                    raise
        if SQL_EMPRESA_MODULO_OVERRIDE_MIGRATION.exists():
            sql_text = SQL_EMPRESA_MODULO_OVERRIDE_MIGRATION.read_text(encoding="utf-8")
            for stmt in split_sql_statements(sql_text):
                try:
                    conn.execute(text(stmt))
                except OperationalError as exc:
                    mysql_code = getattr(getattr(exc, "orig", None), "args", [None])[0]
                    if mysql_code in {1005, 1050, 1060, 1061, 1062, 1091, 1826}:  # fk/table/column/index/dup/drop/constraint
                        continue
                    raise
        if SQL_USUARIO_MODULO_OVERRIDE_MIGRATION.exists():
            sql_text = SQL_USUARIO_MODULO_OVERRIDE_MIGRATION.read_text(encoding="utf-8")
            for stmt in split_sql_statements(sql_text):
                try:
                    conn.execute(text(stmt))
                except OperationalError as exc:
                    mysql_code = getattr(getattr(exc, "orig", None), "args", [None])[0]
                    if mysql_code in {1005, 1050, 1060, 1061, 1062, 1091, 1826}:  # fk/table/column/index/dup/drop/constraint
                        continue
                    raise
        if SQL_INVENTARIO_MODULE_MIGRATION.exists():
            sql_text = SQL_INVENTARIO_MODULE_MIGRATION.read_text(encoding="utf-8")
            for stmt in split_sql_statements(sql_text):
                try:
                    conn.execute(text(stmt))
                except OperationalError as exc:
                    mysql_code = getattr(getattr(exc, "orig", None), "args", [None])[0]
                    if mysql_code in {1005, 1050, 1060, 1061, 1062, 1091, 1826}:  # fk/table/column/index/dup/drop/constraint
                        continue
                    raise
        ensure_inventario_schema(conn)
        empresa_id, rol_id = ensure_admin(conn)

    print("OK: auth migration + admin user created")
    print(f"empresaID={empresa_id}")
    print(f"rolID={rol_id}")
    print(f"login={ADMIN_LOGIN}")
    print(f"email={ADMIN_EMAIL}")
    print(f"password={ADMIN_PASSWORD}")


if __name__ == "__main__":
    main()
