import os
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.permisomodulo import PermisoModulo
from app.models.planmodulo import PlanModulo
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


def auth_schema_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Esquema de autenticación no inicializado. Ejecuta sql/alter_auth_multitenant.sql",
    )


def normalize_module_name(value: str | None) -> str:
    return str(value or "").strip().lower()


def normalize_role_name(value: str | None) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def is_global_join_login(login: str | None) -> bool:
    return str(login or "").strip().lower() in GLOBAL_JOIN_LOGINS


ROLE_SUPER_ADMIN = {"super_admin", "join_superadmin"}
ROLE_EMPRESA_ADMIN = {"empresa_admin", "admin"}


def is_super_admin_context(auth: AuthContext) -> bool:
    return bool(auth.esGlobalJoin) or normalize_role_name(auth.rol) in ROLE_SUPER_ADMIN


def is_empresa_admin_context(auth: AuthContext) -> bool:
    if is_super_admin_context(auth):
        return True
    return normalize_role_name(auth.rol) in ROLE_EMPRESA_ADMIN


def verify_password(plain_password: str, password_hash: str) -> bool:
    if not plain_password or not password_hash:
        return False

    if password_hash.startswith("$2"):
        return pwd_context.verify(plain_password, password_hash)

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


def create_access_token(*, user_id: int, empresa_id: int, sucursal_id: int | None, rol_id: int, plan_id: int | None = None) -> str:
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
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def load_empresa_auth_meta(db: Session, empresa_id: int) -> dict:
    try:
        row = db.execute(
            text("SELECT idEmpresa, planID, estado FROM Empresa WHERE idEmpresa = :empresa_id LIMIT 1"),
            {"empresa_id": int(empresa_id)},
        ).mappings().first()
    except SQLAlchemyError:
        try:
            row = db.execute(
                text("SELECT idEmpresa FROM Empresa WHERE idEmpresa = :empresa_id LIMIT 1"),
                {"empresa_id": int(empresa_id)},
            ).mappings().first()
        except SQLAlchemyError as exc:
            raise auth_schema_error() from exc

        if not row:
            return {"exists": False, "planID": None, "estado": None}
        return {"exists": True, "planID": None, "estado": None}

    if not row:
        return {"exists": False, "planID": None, "estado": None}

    return {
        "exists": True,
        "planID": (int(row.get("planID")) if row.get("planID") is not None else None),
        "estado": row.get("estado"),
    }


def load_empresa_module_overrides(db: Session, empresa_id: int) -> dict[str, bool] | None:
    try:
        rows = db.execute(
            text(
                """
                SELECT modulo, activo
                FROM EmpresaModulo
                WHERE empresaID = :empresa_id
                """
            ),
            {"empresa_id": int(empresa_id)},
        ).mappings().all()
    except SQLAlchemyError:
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
        rows = db.execute(
            text(
                """
                SELECT modulo, activo
                FROM UsuarioModulo
                WHERE userID = :user_id
                """
            ),
            {"user_id": int(user_id)},
        ).mappings().all()
    except SQLAlchemyError:
        return None

    if not rows:
        return None

    return {
        normalize_module_name(row.get("modulo")): bool(row.get("activo"))
        for row in rows
        if row.get("modulo")
    }


def _build_auth_context(db: Session, payload: dict) -> AuthContext:
    user_id = int(payload.get("userID"))
    empresa_id = int(payload.get("empresaID"))
    rol_id = int(payload.get("rolID"))
    sucursal_id = payload.get("sucursalID")
    plan_id = payload.get("planID")

    usuario = (
        db.query(Usuario)
        .filter(
            Usuario.idUsuario == user_id,
            Usuario.empresaID == empresa_id,
            Usuario.estado == "Activo",
        )
        .first()
    )
    if not usuario:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario inválido o inactivo")

    empresa_meta = load_empresa_auth_meta(db, empresa_id)
    if not empresa_meta["exists"] or not is_empresa_activa(empresa_meta.get("estado")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Empresa no activa")

    rol = (
        db.query(Rol)
        .filter(Rol.idRol == rol_id, Rol.empresaID == empresa_id)
        .first()
    )
    if not rol:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Rol inválido para la empresa")

    permisos_rows = db.query(PermisoModulo).filter(PermisoModulo.rolID == rol_id).all()
    permisos: dict[str, dict[str, bool]] = {}
    for row in permisos_rows:
        modulo = normalize_module_name(row.modulo)
        permisos[modulo] = {
            "puedeVer": bool(row.puedeVer),
            "puedeCrear": bool(row.puedeCrear),
            "puedeEditar": bool(row.puedeEditar),
            "puedeEliminar": bool(row.puedeEliminar),
        }

    effective_plan_id = empresa_meta["planID"] if empresa_meta["planID"] is not None else (int(plan_id) if plan_id is not None else None)
    plan_modules_rows = []
    if effective_plan_id is not None:
        plan_modules_rows = db.query(PlanModulo).filter(PlanModulo.planID == effective_plan_id).all()

    if plan_modules_rows:
        modulos_plan = {
            normalize_module_name(row.modulo)
            for row in plan_modules_rows
            if bool(row.activo)
        }
    else:
        # If the plan matrix does not exist yet, do not block modules by plan.
        modulos_plan = set(permisos.keys())

    overrides = load_empresa_module_overrides(db, empresa_id)
    if overrides is not None:
        # Empresa overrides are partial toggles over plan modules, not a full replacement.
        for modulo, activo in overrides.items():
            if bool(activo):
                modulos_plan.add(modulo)
            else:
                modulos_plan.discard(modulo)

    user_overrides = load_usuario_module_overrides(db, user_id)
    if user_overrides is not None:
        modulos_usuario = {modulo for modulo, activo in user_overrides.items() if activo}
        modulos_plan = modulos_plan.intersection(modulos_usuario)

        for modulo, data in permisos.items():
            if modulo not in modulos_usuario:
                data["puedeVer"] = False
                data["puedeCrear"] = False
                data["puedeEditar"] = False
                data["puedeEliminar"] = False

    return AuthContext(
        userID=user_id,
        empresaID=empresa_id,
        sucursalID=(int(usuario.sucursalID) if usuario.sucursalID is not None else (int(sucursal_id) if sucursal_id is not None else None)),
        rolID=rol_id,
        planID=effective_plan_id,
        rol=str(rol.nombreRol or "SinRol"),
        nombre=str(usuario.nombre or ""),
        login=str(usuario.login or ""),
        email=str(usuario.email or ""),
        esGlobalJoin=is_global_join_login(usuario.login),
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
        detail="Token inválido o expirado",
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
        raise auth_schema_error() from exc


def assert_same_empresa(auth: AuthContext, empresa_id: int):
    if int(auth.empresaID) != int(empresa_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acceso denegado por ámbito de empresa")


def require_module_access(module: str, action: str = "puedeVer"):
    module_normalized = normalize_module_name(module)

    def dependency(auth: AuthContext = Depends(get_current_auth_context)) -> AuthContext:
        if module_normalized not in auth.modulosActivosPlan:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Módulo '{module}' no disponible en el plan")

        if not auth.can(module_normalized, action):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Sin permiso {action} para módulo '{module}'")

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
