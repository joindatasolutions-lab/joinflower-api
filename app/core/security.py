import os
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib import exc
from passlib.context import CryptContext
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.rol import Rol
from app.models.usuario import Usuario
from app.schemas.auth import AuthContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

JWT_SECRET = os.getenv("JWT_SECRET", "dev-change-this-secret")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))
GLOBAL_JOIN_LOGINS = {
    value.strip().lower()
    for value in os.getenv("GLOBAL_JOIN_LOGINS", "joinadmin").split(",")
    if value.strip()
}

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def _quote_ident(value: str) -> str:
    return f'"{value}"'


def _schema_table_columns(db: Session) -> dict[str, set[str]]:
    rows = db.execute(
        text(
            """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = 'petalops'
            """
        )
    ).all()

    tables: dict[str, set[str]] = {}
    for table_name, column_name in rows:
        tables.setdefault(str(table_name), set()).add(str(column_name))
    return tables


def _resolve_table_spec(
    db: Session,
    table_candidates: list[str],
    column_candidates: dict[str, list[str]],
) -> tuple[str, dict[str, str]] | tuple[None, None]:
    tables = _schema_table_columns(db)
    lower_tables = {name.lower(): name for name in tables}

    for candidate in table_candidates:
        actual_table = lower_tables.get(candidate.lower())
        if not actual_table:
            continue

        actual_columns = tables[actual_table]
        resolved_columns: dict[str, str] = {}
        complete = True
        for alias, options in column_candidates.items():
            actual_column = next((option for option in options if option in actual_columns), None)
            if not actual_column:
                complete = False
                break
            resolved_columns[alias] = actual_column

        if complete:
            return actual_table, resolved_columns

    return None, None

def _safe_int(value, default=None):
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def auth_schema_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Esquema de autenticaciÃ³n no inicializado. Ejecuta sql/alter_auth_multitenant.sql",
    )


def normalize_module_name(value: str | None) -> str:
    return str(value or "").strip().lower()


def normalize_role_name(value: str | None) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def is_global_join_login(login: str | None) -> bool:
    return str(login or "").strip().lower() in GLOBAL_JOIN_LOGINS


ROLE_SUPER_ADMIN = {"super_admin", "join_superadmin"}
ROLE_EMPRESA_ADMIN = {"empresa_admin", "admin", "empresa_admin_impersonado"}
ROLE_MODULE_LIMITS = {}
ROLE_PERMISSION_BASELINES = {}


def is_super_admin_context(auth: AuthContext) -> bool:
    return bool(auth.esGlobalJoin) or normalize_role_name(auth.rol) in ROLE_SUPER_ADMIN


def is_empresa_admin_context(auth: AuthContext) -> bool:
    if is_super_admin_context(auth):
        return True
    return normalize_role_name(auth.rol) in ROLE_EMPRESA_ADMIN


def apply_role_module_limits(
    role_name: str | None,
    modulos_activos: set[str],
    permisos: dict[str, dict[str, bool]],
) -> tuple[set[str], dict[str, dict[str, bool]]]:
    normalized_role = normalize_role_name(role_name)
    allowed_modules = ROLE_MODULE_LIMITS.get(normalized_role)
    if not allowed_modules:
        return modulos_activos, permisos

    baseline_permissions = ROLE_PERMISSION_BASELINES.get(normalized_role, {})
    limited_modules = {modulo for modulo in modulos_activos if modulo in allowed_modules}
    limited_modules.update(baseline_permissions.keys())
    limited_permissions: dict[str, dict[str, bool]] = {}
    known_modules = set(permisos.keys()).union(allowed_modules).union(baseline_permissions.keys())
    for modulo in known_modules:
        if modulo in allowed_modules:
            limited_permissions[modulo] = {
                **baseline_permissions.get(
                    modulo,
                    {
                        "puedeVer": False,
                        "puedeCrear": False,
                        "puedeEditar": False,
                        "puedeEliminar": False,
                    },
                ),
                **permisos.get(modulo, {}),
            }
            continue
        limited_permissions[modulo] = {
            "puedeVer": False,
            "puedeCrear": False,
            "puedeEditar": False,
            "puedeEliminar": False,
        }
    return limited_modules, limited_permissions


def verify_password(plain_password: str, password_hash: str) -> bool:
    if not plain_password or not password_hash:
        return False

    if password_hash.startswith("$2"):
        try:
            return pwd_context.verify(plain_password, password_hash)
        except (exc.UnknownHashError, ValueError):
            return False

    # Transitional fallback for legacy records with plain passwords.
    return plain_password == password_hash


def is_empresa_activa(estado_value) -> bool:
    """Normalize legacy/new schemas where Empresa.estado can be tinyint or text."""
    if estado_value is None:
        return True

    if isinstance(estado_value, bool):
        return bool(estado_value)

    if isinstance(estado_value, (int, float)):
        # Legacy schemas may store estado as tinyint with varying conventions.
        # Treat binary numeric values as active to avoid false lockouts.
        return int(estado_value) in {0, 1}

    raw = str(estado_value).strip().upper()
    if raw in {"1", "TRUE", "ACTIVO", "ACTIVA"}:
        return True
    if raw in {"0", "FALSE", "INACTIVO", "INACTIVA", "SUSPENDIDO", "SUSPENDIDA"}:
        return False

    # Conservative default for unknown text values.
    return False


def create_access_token(
    *,
    user_id: int,
    empresa_id: int,
    sucursal_id: int | None,
    rol_id: int,
    plan_id: int | None = None,
    extra_claims: dict | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=JWT_EXPIRE_MINUTES)

    payload = {
        "userID": int(user_id),
        "empresaID": int(empresa_id),
        "sucursalID": (int(sucursal_id) if sucursal_id is not None else None),
        "rolID": int(rol_id),
        "planID": (int(plan_id) if plan_id is not None else None),
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def load_empresa_auth_meta(db: Session, empresa_id: int) -> dict:
    table_row = db.execute(
        text(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'petalops'
              AND lower(table_name) = 'empresa'
            ORDER BY CASE WHEN table_name = 'empresa' THEN 0 ELSE 1 END
            LIMIT 1
            """
        )
    ).first()
    if not table_row:
        return {"exists": False, "planID": None, "estado": None}

    table_name = str(table_row[0])

    cols_rows = db.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'petalops'
              AND table_name = :table_name
            """
        ),
        {"table_name": table_name},
    ).all()
    cols = {str(row[0]) for row in cols_rows}

    id_col = (
        "id_empresa" if "id_empresa" in cols
        else ("idempresa" if "idempresa" in cols else ("idEmpresa" if "idEmpresa" in cols else None))
    )
    plan_col = (
        "plan_id" if "plan_id" in cols
        else ("planid" if "planid" in cols else ("planID" if "planID" in cols else None))
    )
    estado_col = "estado" if "estado" in cols else None

    if id_col is None:
        return {"exists": False, "planID": None, "estado": None}

    q_table = f'"{table_name}"'
    q_id_col = f'"{id_col}"'
    plan_select = f'"{plan_col}" AS plan_id' if plan_col else "NULL AS plan_id"
    estado_select = f'"{estado_col}" AS estado' if estado_col else "NULL AS estado"

    try:
        row = db.execute(
            text(
                f"SELECT {q_id_col} AS empresa_id, {plan_select}, {estado_select} "
                f"FROM petalops.{q_table} WHERE {q_id_col} = :empresa_id LIMIT 1"
            ),
            {"empresa_id": int(empresa_id)},
        ).mappings().first()
    except SQLAlchemyError as exc:
        print(f"âŒ ERROR en load_empresa_auth_meta: {exc}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not row:
        return {"exists": False, "planID": None, "estado": None}
    return {
        "exists": True,
        "planID": (int(row.get("plan_id")) if row.get("plan_id") is not None else None),
        "estado": row.get("estado"),
    }

def load_empresa_module_overrides(db: Session, empresa_id: int) -> dict[str, bool] | None:
    try:
        table_name, columns = _resolve_table_spec(
            db,
            ["empresa_modulo", "empresamodulo", "EmpresaModulo"],
            {
                "empresa_id": ["empresa_id", "empresaid", "empresaID"],
                "modulo": ["modulo"],
                "activo": ["activo"],
            },
        )
        if not table_name or not columns:
            return None

        rows = db.execute(
            text(
                f"""
                SELECT {_quote_ident(columns["modulo"])} AS modulo,
                       {_quote_ident(columns["activo"])} AS activo
                FROM petalops.{_quote_ident(table_name)}
                WHERE {_quote_ident(columns["empresa_id"])} = :empresa_id
                """
            ),
            {"empresa_id": int(empresa_id)},
        ).mappings().all()
    except SQLAlchemyError as e:
        print(f"âŒ ERROR en load_empresa_module_overrides: {e}")
        db.rollback()
        return None

    if not rows:
        return None

    return {
        normalize_module_name(row.get("modulo")): bool(row.get("activo"))
        for row in rows
        if row.get("modulo")
    }


def load_usuario_module_overrides(db: Session, user_id: int) -> dict[str, bool] | None:
    try:
        table_name, columns = _resolve_table_spec(
            db,
            ["usuario_modulo", "usuariomodulo", "UsuarioModulo"],
            {
                "user_id": ["usuario_id", "userid", "userID"],
                "modulo": ["modulo"],
                "activo": ["activo"],
            },
        )
        if not table_name or not columns:
            return None

        rows = db.execute(
            text(
                f"""
                SELECT {_quote_ident(columns["modulo"])} AS modulo,
                       {_quote_ident(columns["activo"])} AS activo
                FROM petalops.{_quote_ident(table_name)}
                WHERE {_quote_ident(columns["user_id"])} = :user_id
                """
            ),
            {"user_id": int(user_id)},
        ).mappings().all()
    except SQLAlchemyError as e:
        print(f"âŒ ERROR en load_usuario_module_overrides: {e}")
        db.rollback()
        return None

    if not rows:
        return None

    return {
        normalize_module_name(row.get("modulo")): bool(row.get("activo"))
        for row in rows
        if row.get("modulo")
    }
def _build_auth_context(db: Session, payload: dict) -> AuthContext:
    user_id = _safe_int(payload.get("userID"))
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalido o expirado")

    empresa_id = _safe_int(payload.get("empresaID"), 0)
    rol_id = _safe_int(payload.get("rolID"), 0)
    sucursal_id = payload.get("sucursalID")
    plan_id = payload.get("planID")

    usuario = (
        db.query(Usuario)
        .filter(Usuario.idusuario == user_id)
        .first()
    )
    if not usuario:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario invalido o inactivo")
    if str(usuario.estado or "").strip().upper() != "ACTIVO":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario invalido o inactivo")

    is_superadmin_user = bool(getattr(usuario, "esSuperadmin", False))
    if not is_superadmin_user and is_global_join_login(usuario.login):
        is_superadmin_user = True

    impersonated_empresa_id = _safe_int(payload.get("impersonatedEmpresaID"))
    impersonated = bool(payload.get("impersonated")) and impersonated_empresa_id is not None

    if is_superadmin_user and not impersonated:
        empresa_id = _safe_int(usuario.empresaID, 0)
        rol_id = _safe_int(usuario.rolID, 0)
        effective_plan_id = None
        rol_nombre = "super_admin"
        # Superadmin no depende de plan para acceder a módulos.
        modulos_plan: set[str] = {
            "pipeline",
            "pedidos",
            "produccion",
            "domicilios",
            "catalogo",
            "usuarios",
            "inventario",
            "contabilidad",
            "trazabilidad",
            "reportes",
            "clientes",
        }
        permisos: dict[str, dict[str, bool]] = {
            modulo: {
                "puedeVer": True,
                "puedeCrear": True,
                "puedeEditar": True,
                "puedeEliminar": True,
            }
            for modulo in modulos_plan
        }
    elif is_superadmin_user and impersonated:
        empresa_id = int(impersonated_empresa_id)
        rol_id = _safe_int(payload.get("impersonatedRolID"), 0)

        empresa_meta = load_empresa_auth_meta(db, empresa_id)
        if not empresa_meta["exists"] or not is_empresa_activa(empresa_meta.get("estado")):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Empresa no activa")

        effective_plan_id = (
            empresa_meta["planID"]
            if empresa_meta["planID"] is not None
            else _safe_int(plan_id)
        )
        rol_nombre = "empresa_admin_impersonado"

        modulos_plan: set[str] = set()
        if effective_plan_id is not None:
            plan_table, plan_columns = _resolve_table_spec(
                db,
                ["plan_modulo", "planmodulo", "PlanModulo"],
                {
                    "plan_id": ["plan_id", "planid", "planID"],
                    "modulo": ["modulo"],
                    "activo": ["activo"],
                },
            )
            if plan_table and plan_columns:
                plan_modules_rows = db.execute(
                    text(
                        f"""
                        SELECT {_quote_ident(plan_columns["modulo"])} AS modulo,
                               {_quote_ident(plan_columns["activo"])} AS activo
                        FROM petalops.{_quote_ident(plan_table)}
                        WHERE {_quote_ident(plan_columns["plan_id"])} = :plan_id
                        """
                    ),
                    {"plan_id": int(effective_plan_id)},
                ).mappings().all()
                modulos_plan = {
                    normalize_module_name(row.get("modulo"))
                    for row in plan_modules_rows
                    if bool(row.get("activo"))
                }

        if not modulos_plan:
            modulos_plan = {
                "pipeline",
                "pedidos",
                "produccion",
                "domicilios",
                "catalogo",
                "usuarios",
                "inventario",
                "contabilidad",
                "trazabilidad",
                "reportes",
                "clientes",
            }

        overrides = load_empresa_module_overrides(db, empresa_id)
        if overrides is not None:
            for modulo, activo in overrides.items():
                if bool(activo):
                    modulos_plan.add(modulo)
                else:
                    modulos_plan.discard(modulo)

        permisos = {
            modulo: {
                "puedeVer": True,
                "puedeCrear": True,
                "puedeEditar": True,
                "puedeEliminar": True,
            }
            for modulo in modulos_plan
        }
    else:
        if usuario.empresaID is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario invalido o inactivo")
        if int(usuario.empresaID) != int(empresa_id):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalido o expirado")

        empresa_meta = load_empresa_auth_meta(db, empresa_id)
        if not empresa_meta["exists"] or not is_empresa_activa(empresa_meta.get("estado")):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Empresa no activa")

        rol = (
            db.query(Rol)
            .filter(Rol.idRol == rol_id, Rol.empresaID == empresa_id)
            .first()
        )
        if not rol:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Rol invalido para la empresa")

        rol_nombre = str(rol.nombreRol or "SinRol")

        permiso_table, permiso_columns = _resolve_table_spec(
            db,
            ["permiso_modulo", "permisomodulo", "PermisoModulo"],
            {
                "rol_id": ["rol_id", "rolid", "rolID"],
                "modulo": ["modulo"],
                "puede_ver": ["puede_ver", "puedever", "puedeVer"],
                "puede_crear": ["puede_crear", "puedecrear", "puedeCrear"],
                "puede_editar": ["puede_editar", "puedeeditar", "puedeEditar"],
                "puede_eliminar": ["puede_eliminar", "puedeeliminar", "puedeEliminar"],
            },
        )
        permisos_rows = []
        if permiso_table and permiso_columns:
            permisos_rows = db.execute(
                text(
                    f"""
                    SELECT {_quote_ident(permiso_columns["modulo"])} AS modulo,
                           {_quote_ident(permiso_columns["puede_ver"])} AS puede_ver,
                           {_quote_ident(permiso_columns["puede_crear"])} AS puede_crear,
                           {_quote_ident(permiso_columns["puede_editar"])} AS puede_editar,
                           {_quote_ident(permiso_columns["puede_eliminar"])} AS puede_eliminar
                    FROM petalops.{_quote_ident(permiso_table)}
                    WHERE {_quote_ident(permiso_columns["rol_id"])} = :rol_id
                    """
                ),
                {"rol_id": int(rol_id)},
            ).mappings().all()
        permisos = {}
        for row in permisos_rows:
            modulo = normalize_module_name(row.get("modulo"))
            permisos[modulo] = {
                "puedeVer": bool(row.get("puede_ver")),
                "puedeCrear": bool(row.get("puede_crear")),
                "puedeEditar": bool(row.get("puede_editar")),
                "puedeEliminar": bool(row.get("puede_eliminar")),
            }

        effective_plan_id = (
            empresa_meta["planID"]
            if empresa_meta["planID"] is not None
            else _safe_int(plan_id)
        )
        plan_modules_rows = []
        if effective_plan_id is not None:
            plan_table, plan_columns = _resolve_table_spec(
                db,
                ["plan_modulo", "planmodulo", "PlanModulo"],
                {
                    "plan_id": ["plan_id", "planid", "planID"],
                    "modulo": ["modulo"],
                    "activo": ["activo"],
                },
            )
            if plan_table and plan_columns:
                plan_modules_rows = db.execute(
                    text(
                        f"""
                        SELECT {_quote_ident(plan_columns["modulo"])} AS modulo,
                               {_quote_ident(plan_columns["activo"])} AS activo
                        FROM petalops.{_quote_ident(plan_table)}
                        WHERE {_quote_ident(plan_columns["plan_id"])} = :plan_id
                        """
                    ),
                    {"plan_id": int(effective_plan_id)},
                ).mappings().all()

        if plan_modules_rows:
            modulos_plan = {
                normalize_module_name(row.get("modulo"))
                for row in plan_modules_rows
                if bool(row.get("activo"))
            }
        else:
            modulos_plan = set(permisos.keys())

        overrides = load_empresa_module_overrides(db, empresa_id)
        if overrides is not None:
            for modulo, activo in overrides.items():
                if bool(activo):
                    modulos_plan.add(modulo)
                else:
                    modulos_plan.discard(modulo)

        user_overrides = load_usuario_module_overrides(db, user_id)
        if user_overrides is not None:
            modulos_usuario = {modulo for modulo, activo in user_overrides.items() if activo}
            modulos_plan = modulos_plan.intersection(modulos_usuario)

            for modulo in modulos_plan:
                permisos[modulo] = {
                    "puedeVer": True,
                    "puedeCrear": True,
                    "puedeEditar": True,
                    "puedeEliminar": bool(permisos.get(modulo, {}).get("puedeEliminar", False)),
                }

            for modulo, data in permisos.items():
                if modulo not in modulos_usuario:
                    data["puedeVer"] = False
                    data["puedeCrear"] = False
                    data["puedeEditar"] = False
                    data["puedeEliminar"] = False

        modulos_plan, permisos = apply_role_module_limits(rol_nombre, modulos_plan, permisos)

    return AuthContext(
        userID=user_id,
        empresaID=empresa_id,
        sucursalID=(_safe_int(usuario.sucursalID) if usuario.sucursalID is not None else _safe_int(sucursal_id)),
        rolID=rol_id,
        planID=effective_plan_id,
        rol=rol_nombre,
        nombre=str(usuario.nombre or ""),
        login=str(usuario.login or ""),
        email=str(usuario.email or ""),
        esGlobalJoin=(is_global_join_login(usuario.login) or is_superadmin_user) and not impersonated,
        ultimoLogin=usuario.ultimoLogin,
        permisos=permisos,
        modulosActivosPlan=modulos_plan,
    )
def get_current_auth_context(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> AuthContext:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token invalido o expirado",
    )

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError as exc:
        raise credentials_error from exc

    required = ["userID", "empresaID", "rolID"]
    if any(payload.get(key) is None for key in required):
        raise credentials_error

    try:
        return _build_auth_context(db, payload)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


def assert_same_empresa(auth: AuthContext, empresa_id: int):
    if is_super_admin_context(auth):
        return
    if int(auth.empresaID) != int(empresa_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acceso denegado por Ã¡mbito de empresa")


def require_module_access(module: str, action: str = "puedeVer"):
    module_normalized = normalize_module_name(module)

    def dependency(auth: AuthContext = Depends(get_current_auth_context)) -> AuthContext:
        if is_super_admin_context(auth):
            return auth

        if module_normalized not in auth.modulosActivosPlan:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"MÃ³dulo '{module}' no disponible en el plan")

        if not auth.can(module_normalized, action):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Sin permiso {action} para mÃ³dulo '{module}'")

        return auth

    return dependency


def require_admin_role(auth: AuthContext = Depends(get_current_auth_context)) -> AuthContext:
    if not is_empresa_admin_context(auth):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo rol Admin puede gestionar usuarios")
    return auth


def require_global_join_user(auth: AuthContext = Depends(get_current_auth_context)) -> AuthContext:
    if not is_super_admin_context(auth):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo usuario global JOIN puede acceder")
    return auth


