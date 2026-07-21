from datetime import datetime, timezone
import json
import os
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.core.security import (
    JWT_EXPIRE_MINUTES,
    _quote_ident,
    _resolve_table_spec,
    auth_schema_error,
    create_access_token,
    get_current_auth_context,
    load_empresa_auth_meta,
    load_usuario_module_overrides,
    pwd_context,
    require_admin_role,
    is_empresa_admin_context,
    is_super_admin_context,
    normalize_module_name,
    normalize_role_name,
    is_empresa_activa,
    require_global_join_user,
    verify_password,
)
from app.database import get_db
from app.middlewares.rate_limit import limiter
from app.models.rol import Rol
from app.models.sucursal import Sucursal
from app.models.usuario import Usuario
from app.services.cache import get_cache, set_cache
from app.services.empresa_menu_service import sync_empresa_menu_opciones
from app.schemas.auth import (
    AuthMeResponse,
    EmpresaCreateRequest,
    EmpresaCreateResponse,
    EmpresaListResponse,
    EmpresaModuloResumenItem,
    EmpresaModuloResumenResponse,
    EmpresaModuloListResponse,
    EmpresaModuloItem,
    EmpresaModuloUpdateRequest,
    EmpresaModuloUpdateResponse,
    EmpresaOption,
    LoginRequest,
    LoginResponse,
    ImpersonateRequest,
    RoleListResponse,
    RoleOption,
    SucursalListResponse,
    SucursalOption,
    UserCreateRequest,
    UserCreateResponse,
    UserDeleteResponse,
    UserDetailResponse,
    UserListItem,
    UserListResponse,
    UserStatusUpdateRequest,
    UserUpdateRequest,
)

router = APIRouter(prefix="/auth", tags=["Auth"])
auth_logger = get_logger("auth")


def _err(code: str, message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "module": "auth"},
    )


STRUCTURAL_ROLES = {"super_admin", "join_superadmin", "empresa_admin", "admin"}
DEFAULT_MODULES = {
    "pipeline",
    "pedidos",
    "produccion",
    "domicilios",
    "inventario",
    "contabilidad",
    "trazabilidad",
    "clientes",
    "usuarios",
    "catalogo",
    "reportes",
}

DEFAULT_ROLE_MODULE_POLICY = {
    "Admin": {
        "pipeline": (1, 1, 1, 1),
        "pedidos": (1, 1, 1, 1),
        "produccion": (1, 1, 1, 1),
        "domicilios": (1, 1, 1, 1),
        "catalogo": (1, 1, 1, 1),
        "usuarios": (1, 1, 1, 1),
        "inventario": (1, 1, 1, 1),
        "contabilidad": (1, 1, 1, 1),
        "trazabilidad": (1, 1, 1, 1),
        "clientes": (1, 1, 1, 1),
    },
    "Florista": {
        "produccion": (1, 1, 1, 0),
        "catalogo": (1, 0, 0, 0),
    },
    "Pedidos": {
        "pedidos": (1, 1, 1, 0),
        "domicilios": (1, 1, 1, 0),
    },
    "Recepcion": {
        "pedidos": (1, 1, 1, 0),
    },
    "Domiciliario": {
        "domicilios": (1, 1, 1, 0),
    },
    "Inventarista": {
        "catalogo": (1, 1, 1, 0),
        "inventario": (1, 1, 1, 0),
    },
    "Contabilidad": {
        "contabilidad": (1, 1, 1, 0),
    },
    "Operativo": {
        "pedidos": (1, 1, 0, 0),
        "produccion": (1, 1, 0, 0),
        "inventario": (1, 0, 0, 0),
        "pipeline": (1, 0, 0, 0),
    },
}

def _safe_int(value, default=None):
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _ensure_empresa_modulo_table(db: Session):
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS petalops.empresa_modulo (
              empresa_id BIGINT NOT NULL,
              modulo VARCHAR(80) NOT NULL,
              activo BOOLEAN NOT NULL DEFAULT TRUE,
              updatedat TIMESTAMP NOT NULL,
              PRIMARY KEY (empresa_id, modulo),
              CONSTRAINT fk_empresamodulo_empresa FOREIGN KEY (empresa_id)
                REFERENCES petalops.empresa(id_empresa)
            );
            """
        )
    )
    db.execute(text("CREATE INDEX IF NOT EXISTS idx_empresa_modulo_activo ON petalops.empresa_modulo (empresa_id, activo);"))


def _ensure_usuario_modulo_table(db: Session):
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS petalops.usuario_modulo (
              usuario_id BIGINT NOT NULL,
              modulo VARCHAR(80) NOT NULL,
              activo BOOLEAN NOT NULL DEFAULT TRUE,
              updated_at TIMESTAMP NOT NULL,
              PRIMARY KEY (usuario_id, modulo),
              CONSTRAINT fk_usuariomodulo_usuario FOREIGN KEY (usuario_id)
                REFERENCES petalops.usuario(id_usuario)
            );
            """
        )
    )
    db.execute(text("CREATE INDEX IF NOT EXISTS idx_usuariomodulo_activo ON petalops.usuario_modulo (usuario_id, activo);"))


def _plan_user_limit(plan_id: int | None) -> int:
    raw = os.getenv("PLAN_USER_LIMITS_JSON", "")
    if raw:
        try:
            parsed = json.loads(raw)
            value = parsed.get(str(int(plan_id or 0)))
            if value is not None:
                return max(int(value), 1)
        except Exception:
            pass

    defaults = {
        0: 20,
        1: 20,
        2: 80,
        3: 250,
    }
    return defaults.get(int(plan_id or 0), 20)


def _audit_user_action(db: Session, actor, action: str, target: Usuario, extra: dict | None = None):
    payload = json.dumps(extra or {}, ensure_ascii=True)
    table_name, columns = _resolve_table_spec(
        db,
        ["usuario_auditoria", "usuarioauditoria", "UsuarioAuditoria"],
        {
            "empresa_id": ["empresa_id", "empresaid", "empresaID"],
            "actor_user_id": ["actor_user_id", "actoruserid", "actorUserID"],
            "actor_login": ["actor_login", "actorlogin", "actorLogin"],
            "accion": ["accion"],
            "target_user_id": ["target_user_id", "targetuserid", "targetUserID"],
            "target_login": ["target_login", "targetlogin", "targetLogin"],
            "detalle_json": ["detalle_json", "detallejson", "detalleJSON"],
            "created_at": ["created_at", "createdat", "createdAt"],
        },
    )
    if not table_name or not columns:
        return

    db.execute(
        text(
            f"""
            INSERT INTO petalops.{_quote_ident(table_name)} (
                {_quote_ident(columns["empresa_id"])},
                {_quote_ident(columns["actor_user_id"])},
                {_quote_ident(columns["actor_login"])},
                {_quote_ident(columns["accion"])},
                {_quote_ident(columns["target_user_id"])},
                {_quote_ident(columns["target_login"])},
                {_quote_ident(columns["detalle_json"])},
                {_quote_ident(columns["created_at"])}
            )
            VALUES (
                :empresa_id,
                :actor_user_id,
                :actor_login,
                :accion,
                :target_user_id,
                :target_login,
                :detalle,
                CURRENT_TIMESTAMP
            )
            """
        ),
        {
            "empresa_id": int(target.empresaID),
            "actor_user_id": int(actor.userID),
            "actor_login": str(actor.login),
            "accion": action,
            "target_user_id": int(target.idusuario),
            "target_login": str(target.login),
            "detalle": payload,
        },
    )


def _resolve_empresa_id_for_module_admin(db: Session, empresa_id: int) -> int:
    empresa_meta = load_empresa_auth_meta(db, int(empresa_id))
    if not empresa_meta.get("exists"):
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    return int(empresa_id)


def _load_empresa_columns(db: Session) -> set[str]:
    rows = db.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'petalops'
              AND table_name = 'empresa'
            """
        )
    ).all()
    return {str(row[0]) for row in rows}


def _build_empresa_module_items(db: Session, empresa_id: int) -> list[EmpresaModuloItem]:
    empresa_meta = load_empresa_auth_meta(db, empresa_id)
    effective_plan_id = empresa_meta.get("planID")

    module_candidates = set(DEFAULT_MODULES)
    has_plan_rows = False

    if effective_plan_id is not None:
        try:
            plan_rows = db.execute(
                text("SELECT modulo, activo FROM petalops.plan_modulo WHERE plan_id = :plan_id"),
                {"plan_id": int(effective_plan_id)},
            ).all()
            has_plan_rows = len(plan_rows) > 0
            for modulo, _activo in plan_rows:
                module_candidates.add(normalize_module_name(modulo))
        except SQLAlchemyError:
            plan_rows = []

    try:
        permiso_rows = db.execute(
            text(
                """
                SELECT DISTINCT pm.modulo
                FROM petalops.permiso_modulo pm
                JOIN petalops.rol r ON r.id_rol = pm.rol_id
                WHERE r.empresa_id = :empresa_id
                """
            ),
            {"empresa_id": int(empresa_id)},
        ).all()
        for (modulo,) in permiso_rows:
            module_candidates.add(normalize_module_name(modulo))
    except SQLAlchemyError:
        permiso_rows = []

    _ensure_empresa_modulo_table(db)
    override_rows = db.execute(
        text("SELECT modulo, activo FROM petalops.empresa_modulo WHERE empresa_id = :empresa_id"),
        {"empresa_id": int(empresa_id)},
    ).all()
    overrides = {}
    for modulo, activo in override_rows:
        key = normalize_module_name(modulo)
        if not key:
            continue
        overrides[key] = bool(activo)
        module_candidates.add(key)

    active_from_plan = set()
    if effective_plan_id is not None:
        try:
            active_rows = db.execute(
                text("SELECT modulo FROM petalops.plan_modulo WHERE plan_id = :plan_id AND activo = TRUE"),
                {"plan_id": int(effective_plan_id)},
            ).all()
            active_from_plan = {normalize_module_name(modulo) for (modulo,) in active_rows}
        except SQLAlchemyError:
            active_rows = []

    if not has_plan_rows:
        active_from_plan = set(DEFAULT_MODULES)

    items = []
    for modulo in sorted({m for m in module_candidates if m}):
        activo = overrides.get(modulo, modulo in active_from_plan)
        items.append(EmpresaModuloItem(modulo=modulo, activo=bool(activo)))
    return items


def _normalize_module_list(values: list[str] | None) -> list[str]:
    if values is None:
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for raw in values:
        module = normalize_module_name(raw)
        if not module or module in seen:
            continue
        seen.add(module)
        normalized.append(module)
    return normalized


def _validate_user_modules(db: Session, empresa_id: int, values: list[str] | None) -> list[str]:
    requested_modules = _normalize_module_list(values)
    available_modules = {
        item.modulo
        for item in _build_empresa_module_items(db, int(empresa_id))
        if bool(item.activo)
    }
    invalid_modules = sorted(set(requested_modules) - available_modules)
    if invalid_modules:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "Modulos invalidos o no disponibles para la empresa",
                "modulosInvalidos": invalid_modules,
            },
        )
    return requested_modules


def _user_email_or_default(raw_email: str | None, login: str, user_id: int | None = None) -> str:
    email = str(raw_email or "").strip().lower()
    if email:
        return email
    safe_login = re.sub(r"[^a-z0-9._-]+", "_", str(login or "").strip().lower()).strip("._-")
    if not safe_login:
        safe_login = f"usuario_{user_id}" if user_id is not None else "usuario"
    return f"{safe_login}@petalops.local"


def _load_role_viewable_modules(db: Session, rol_id: int) -> set[str]:
    permiso_table, permiso_columns = _resolve_table_spec(
        db,
        ["permiso_modulo", "permisomodulo", "PermisoModulo"],
        {
            "rol_id": ["rol_id", "rolid", "rolID"],
            "modulo": ["modulo"],
            "puede_ver": ["puede_ver", "puedever", "puedeVer"],
        },
    )
    if not permiso_table or not permiso_columns:
        return set()

    rows = db.execute(
        text(
            f"""
            SELECT {_quote_ident(permiso_columns["modulo"])} AS modulo
            FROM petalops.{_quote_ident(permiso_table)}
            WHERE {_quote_ident(permiso_columns["rol_id"])} = :rol_id
              AND {_quote_ident(permiso_columns["puede_ver"])} = TRUE
            """
        ),
        {"rol_id": int(rol_id)},
    ).mappings().all()

    return {
        normalize_module_name(row.get("modulo"))
        for row in rows
        if row.get("modulo")
    }


def _get_target_user_for_admin(db: Session, auth, user_id: int) -> tuple[Usuario, Rol | None]:
    usuario = db.query(Usuario).filter(Usuario.idusuario == user_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    if not is_super_admin_context(auth) and int(usuario.empresaID or 0) != int(auth.empresaID):
        raise HTTPException(status_code=403, detail="No puedes modificar usuarios de otra empresa")

    target_role = db.query(Rol).filter(Rol.idRol == usuario.rolID).first()
    if target_role:
        target_role_name = normalize_role_name(target_role.nombreRol)
        if not is_super_admin_context(auth) and target_role_name in STRUCTURAL_ROLES:
            raise HTTPException(status_code=403, detail="No puedes modificar usuarios de rol estructural")

    return usuario, target_role


def _load_user_modules(db: Session, user_id: int, role_name: str | None = None) -> list[str]:
    overrides = load_usuario_module_overrides(db, int(user_id))
    if not overrides:
        return []
    modules = {modulo for modulo, activo in overrides.items() if bool(activo)}
    return sorted(modules)


def _next_florista_internal_number(db: Session, empresa_id: int, sucursal_id: int | None) -> int:
    row = db.execute(
        text(
            """
            SELECT COALESCE(MAX(pf.numero_interno), 0)
            FROM petalops.perfil_florista pf
            JOIN petalops.empleado e
              ON e.id_empleado = pf.empleado_id
            WHERE e.empresa_id = :empresa_id
              AND upper(COALESCE(e.cargo, '')) = 'FLORISTA'
              AND (:sucursal_id IS NULL OR e.sucursal_id = :sucursal_id)
            """
        ),
        {
            "empresa_id": int(empresa_id),
            "sucursal_id": (int(sucursal_id) if sucursal_id is not None else None),
        },
    ).first()
    return int((row[0] if row and row[0] is not None else 0)) + 1


def _employee_sync_email_value(db: Session, usuario: Usuario, empleado_id: int | None = None) -> str:
    requested_email = str(usuario.email or "").strip().lower()
    if requested_email:
        duplicate = db.execute(
            text(
                """
                SELECT id_empleado
                FROM petalops.empleado
                WHERE empresa_id = :empresa_id
                  AND lower(COALESCE(email, '')) = :email
                  AND (:empleado_id IS NULL OR id_empleado <> :empleado_id)
                LIMIT 1
                """
            ),
            {
                "empresa_id": int(usuario.empresaID),
                "email": requested_email,
                "empleado_id": (int(empleado_id) if empleado_id is not None else None),
            },
        ).first()
        if not duplicate:
            return requested_email

    login_base = str(usuario.login or "").strip().lower().replace(" ", "")
    if not login_base:
        login_base = f"user{int(usuario.idusuario)}"
    return f"{login_base}+emp{int(usuario.empresaID)}@empleado.local"


def _sync_employee_profile_for_operational_user(db: Session, usuario: Usuario, rol_nombre: str) -> None:
    role_name = normalize_role_name(rol_nombre)
    cargo = str(rol_nombre or "").strip() or "Operativo"
    is_florista_role = role_name == "florista"

    empleado = db.execute(
        text(
            """
            SELECT id_empleado
            FROM petalops.empleado
            WHERE usuario_id = :usuario_id
            ORDER BY id_empleado ASC
            LIMIT 1
            """
        ),
        {"usuario_id": int(usuario.idusuario)},
    ).mappings().first()

    empleado_id: int | None = int(empleado["id_empleado"]) if empleado else None
    activo_flag = 1 if str(usuario.estado or "").strip().lower() == "activo" else 0
    employee_email = _employee_sync_email_value(db, usuario, empleado_id)

    if empleado_id is None:
        empleado_id = int(
            db.execute(
                text(
                    """
                    INSERT INTO petalops.empleado (
                        empresa_id, sucursal_id, nombre_empleado, cargo, activo,
                        created_at, updated_at, usuario, email, password_hash, usuario_id, is_superuser
                    )
                    VALUES (
                        :empresa_id, :sucursal_id, :nombre_empleado, :cargo, :activo,
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, :usuario_login, :email, :password_hash, :usuario_id, 0
                    )
                    RETURNING id_empleado
                    """
                ),
                {
                    "empresa_id": int(usuario.empresaID),
                    "sucursal_id": int(usuario.sucursalID),
                    "nombre_empleado": str(usuario.nombre or "").strip(),
                    "cargo": cargo,
                    "activo": activo_flag,
                    "usuario_login": str(usuario.login or "").strip(),
                    "email": employee_email,
                    "password_hash": str(usuario.passwordHash or "").strip(),
                    "usuario_id": int(usuario.idusuario),
                },
            ).scalar()
        )
    else:
        db.execute(
            text(
                """
                UPDATE petalops.empleado
                SET empresa_id = :empresa_id,
                    sucursal_id = :sucursal_id,
                    nombre_empleado = :nombre_empleado,
                    cargo = :cargo,
                    activo = :activo,
                    updated_at = CURRENT_TIMESTAMP,
                    usuario = :usuario_login,
                    email = :email,
                    password_hash = :password_hash
                WHERE id_empleado = :empleado_id
                """
            ),
            {
                "empleado_id": int(empleado_id),
                "empresa_id": int(usuario.empresaID),
                "sucursal_id": int(usuario.sucursalID),
                "nombre_empleado": str(usuario.nombre or "").strip(),
                "cargo": cargo,
                "activo": activo_flag,
                "usuario_login": str(usuario.login or "").strip(),
                "email": employee_email,
                "password_hash": str(usuario.passwordHash or "").strip(),
            },
        )

    if is_florista_role:
        existing_profile = db.execute(
            text(
                """
                SELECT empleado_id, numero_interno
                FROM petalops.perfil_florista
                WHERE empleado_id = :empleado_id
                LIMIT 1
                """
            ),
            {"empleado_id": int(empleado_id)},
        ).first()
        if not existing_profile:
            numero_interno = _next_florista_internal_number(
                db,
                empresa_id=int(usuario.empresaID),
                sucursal_id=(int(usuario.sucursalID) if usuario.sucursalID is not None else None),
            )
            db.execute(
                text(
                    """
                    INSERT INTO petalops.perfil_florista (
                        empleado_id, numero_interno, capacidad_diaria, trab_simul_permi, especialidades, fecha_ini_incap, fecha_fin_incap
                    )
                    VALUES (
                        :empleado_id, :numero_interno, :capacidad_diaria, :trab_simul_permi, NULL, NULL, NULL
                    )
                    """
                ),
                {
                    "empleado_id": int(empleado_id),
                    "numero_interno": int(numero_interno),
                    "capacidad_diaria": 12,
                    "trab_simul_permi": 1,
                },
            )
        elif existing_profile[1] is None:
            numero_interno = _next_florista_internal_number(
                db,
                empresa_id=int(usuario.empresaID),
                sucursal_id=(int(usuario.sucursalID) if usuario.sucursalID is not None else None),
            )
            db.execute(
                text(
                    """
                    UPDATE petalops.perfil_florista
                    SET numero_interno = :numero_interno
                    WHERE empleado_id = :empleado_id
                    """
                ),
                {
                    "empleado_id": int(empleado_id),
                    "numero_interno": int(numero_interno),
                },
            )


def _ensure_default_operational_roles(db: Session, empresa_id: int):
    for role_name, module_policy in DEFAULT_ROLE_MODULE_POLICY.items():
        db.execute(
            text(
                """
                INSERT INTO petalops.rol (empresa_id, nombre_rol)
                VALUES (:empresa_id, :nombre_rol)
                ON CONFLICT (empresa_id, nombre_rol) DO UPDATE SET nombre_rol = EXCLUDED.nombre_rol
                """
            ),
            {"empresa_id": int(empresa_id), "nombre_rol": role_name},
        )

        role_row = db.execute(
            text(
                """
                SELECT id_rol
                FROM petalops.rol
                WHERE empresa_id = :empresa_id AND nombre_rol = :nombre_rol
                LIMIT 1
                """
            ),
            {"empresa_id": int(empresa_id), "nombre_rol": role_name},
        ).first()
        if not role_row:
            continue

        role_id = int(role_row[0])
        for modulo, perms in module_policy.items():
            puede_ver, puede_crear, puede_editar, puede_eliminar = perms
            db.execute(
                text(
                    """
                    INSERT INTO petalops.permiso_modulo
                    (rol_id, modulo, puede_ver, puede_crear, puede_editar, puede_eliminar, empresa_id)
                    VALUES
                    (:rol_id,:modulo,:puede_ver,:puede_crear,:puede_editar,:puede_eliminar,:empresa_id)
                    ON CONFLICT (rol_id, modulo) DO UPDATE SET
                      puede_ver = EXCLUDED.puede_ver,
                      puede_crear = EXCLUDED.puede_crear,
                      puede_editar = EXCLUDED.puede_editar,
                      puede_eliminar = EXCLUDED.puede_eliminar
                    """
                ),
                {
                    "rol_id": role_id,
                    "modulo": normalize_module_name(modulo),
                    "puede_ver": bool(puede_ver),
                    "puede_crear": bool(puede_crear),
                    "puede_editar": bool(puede_editar),
                    "puede_eliminar": bool(puede_eliminar),
                    "empresa_id": int(empresa_id)
                },
            )


@router.post("/login", response_model=LoginResponse)
@limiter.limit("30/minute")
def login(request: Request, payload: LoginRequest, db: Session = Depends(get_db)):
    try:
        usuario = (
            db.query(Usuario)
            .filter(func.lower(Usuario.login) == payload.login.strip().lower())
            .first()
        )
        if not usuario:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales invalidas")

        is_superadmin_user = bool(getattr(usuario, "esSuperadmin", False))
        empresa_id = _safe_int(usuario.empresaID)
        rol_id = _safe_int(usuario.rolID)

        if str(usuario.estado or "").strip().upper() != "ACTIVO":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuario inactivo")

        if not verify_password(payload.password, str(usuario.passwordHash or "")):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales invalidas")

        if is_superadmin_user:
            empresa_meta = {"exists": True, "planID": None, "estado": "ACTIVA"}
        else:
            if empresa_id is None:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuario sin empresa asignada")
            if rol_id is None:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuario sin rol asignado")

            empresa_meta = load_empresa_auth_meta(db, empresa_id)
            if not empresa_meta["exists"]:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales invalidas")

            if not is_empresa_activa(empresa_meta.get("estado")):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Empresa suspendida o inactiva")

            rol = (
                db.query(Rol)
                .filter(Rol.idRol == rol_id, Rol.empresaID == empresa_id)
                .first()
            )
            if not rol:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Rol invalido para la empresa")

        usuario.ultimoLogin = datetime.now(timezone.utc)
        usuario.updatedAt = datetime.now(timezone.utc)
        db.commit()

        user_id = _safe_int(usuario.idusuario)
        if user_id is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Usuario sin identificador valido")

        token = create_access_token(
            user_id=user_id,
            empresa_id=(empresa_id if empresa_id is not None else 0),
            sucursal_id=_safe_int(usuario.sucursalID),
            rol_id=(rol_id if rol_id is not None else 0),
            plan_id=empresa_meta["planID"],
        )

        auth_context = get_current_auth_context(token=token, db=db)

        return LoginResponse(
            accessToken=token,
            expiresIn=JWT_EXPIRE_MINUTES * 60,
            user=AuthMeResponse(**auth_context.to_me_response()),
        )
    except SQLAlchemyError as exc:
        auth_logger.error("Error SQL en login", exc_info=True)
        raise _err("AUTH_LOGIN_DB_ERROR", "Error interno del servidor", status_code=500)

@router.get("/me", response_model=AuthMeResponse)
def me(auth=Depends(get_current_auth_context)):
    return AuthMeResponse(**auth.to_me_response())


@router.post("/impersonate", response_model=LoginResponse)
def impersonate_empresa(
    payload: ImpersonateRequest,
    db: Session = Depends(get_db),
    auth=Depends(require_global_join_user),
):
    empresa_id = int(payload.empresaID)
    empresa_meta = load_empresa_auth_meta(db, empresa_id)
    if not empresa_meta.get("exists"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Empresa no encontrada")
    if not is_empresa_activa(empresa_meta.get("estado")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Empresa suspendida o inactiva")

    superadmin = db.query(Usuario).filter(Usuario.idusuario == int(auth.userID)).first()
    if not superadmin:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Superusuario no encontrado")

    token = create_access_token(
        user_id=int(superadmin.idusuario),
        empresa_id=empresa_id,
        sucursal_id=(int(payload.sucursalID) if payload.sucursalID is not None else None),
        rol_id=(int(superadmin.rolID) if superadmin.rolID is not None else 0),
        plan_id=empresa_meta.get("planID"),
        extra_claims={
            "impersonated": True,
            "impersonatedEmpresaID": empresa_id,
            "impersonatedSucursalID": (int(payload.sucursalID) if payload.sucursalID is not None else None),
            "impersonatedRolID": 0,
        },
    )
    auth_context = get_current_auth_context(token=token, db=db)
    return LoginResponse(
        accessToken=token,
        expiresIn=JWT_EXPIRE_MINUTES * 60,
        user=AuthMeResponse(**auth_context.to_me_response()),
    )


@router.post("/impersonate/stop", response_model=LoginResponse)
def stop_impersonation(
    db: Session = Depends(get_db),
    auth=Depends(require_global_join_user),
):
    superadmin = db.query(Usuario).filter(Usuario.idusuario == int(auth.userID)).first()
    if not superadmin:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Superusuario no encontrado")

    token = create_access_token(
        user_id=int(superadmin.idusuario),
        empresa_id=0,
        sucursal_id=None,
        rol_id=0,
        plan_id=None,
    )
    auth_context = get_current_auth_context(token=token, db=db)
    return LoginResponse(
        accessToken=token,
        expiresIn=JWT_EXPIRE_MINUTES * 60,
        user=AuthMeResponse(**auth_context.to_me_response()),
    )


@router.post("/usuarios", response_model=UserCreateResponse)
def crear_usuario(
    payload: UserCreateRequest,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    try:
        if not is_empresa_admin_context(auth):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos para crear usuarios")

        target_empresa_id = int(payload.empresaID) if payload.empresaID is not None else int(auth.empresaID)
        if not is_super_admin_context(auth) and target_empresa_id != int(auth.empresaID):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No puedes crear usuarios para otra empresa")

        _ensure_default_operational_roles(db, target_empresa_id)

        login = payload.login.strip().lower()
        email = _user_email_or_default(payload.email, login)
        estado = (payload.estado or "Activo").strip().title()
        if estado not in {"Activo", "Inactivo"}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="estado debe ser Activo o Inactivo")

        existing_login = db.query(Usuario).filter(Usuario.login == login).first()
        if existing_login:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Login ya existe")

        rol = (
            db.query(Rol)
            .filter(Rol.idRol == payload.rolID, Rol.empresaID == target_empresa_id)
            .first()
        )
        if not rol:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rol invalido para la empresa")

        role_name = normalize_role_name(rol.nombreRol)
        if not is_super_admin_context(auth) and role_name in STRUCTURAL_ROLES:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Empresa Admin no puede crear roles estructurales")

        empresa_meta = load_empresa_auth_meta(db, target_empresa_id)
        active_users = (
            db.query(func.count(Usuario.idusuario))
            .filter(Usuario.empresaID == target_empresa_id, Usuario.estado == "Activo")
            .scalar()
        )
        max_users = _plan_user_limit(empresa_meta.get("planID"))
        if int(active_users or 0) >= max_users:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"LÃ­mite de usuarios alcanzado para el plan ({max_users})")

        sucursal = db.query(Sucursal).filter(Sucursal.idSucursal == payload.sucursalID).first()
        if not sucursal:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Sucursal invalida")

        selected_user_modules = _validate_user_modules(db, target_empresa_id, payload.modulosAcceso)

        usuario = Usuario(
            empresaID=target_empresa_id,
            sucursalID=int(payload.sucursalID),
            nombre=payload.nombre.strip(),
            login=login,
            email=email,
            passwordHash=pwd_context.hash(payload.password),
            rolID=int(payload.rolID),
            estado=estado,
            createdAt=datetime.now(timezone.utc),
            updatedAt=datetime.now(timezone.utc),
        )
        db.add(usuario)
        db.flush()
        _sync_employee_profile_for_operational_user(db, usuario, str(rol.nombreRol or ""))
        if payload.modulosAcceso is not None:
            _ensure_usuario_modulo_table(db)
            db.execute(
                text("DELETE FROM petalops.usuario_modulo WHERE usuario_id = :user_id"),
                {"user_id": int(usuario.idusuario)},
            )
            for modulo in selected_user_modules:
                db.execute(
                    text(
                        """
                        INSERT INTO petalops.usuario_modulo (usuario_id, modulo, activo, updated_at)
                        VALUES (:user_id, :modulo, TRUE, CURRENT_TIMESTAMP)
                        """
                    ),
                    {"user_id": int(usuario.idusuario), "modulo": modulo},
                )
        _audit_user_action(
            db,
            actor=auth,
            action="USER_CREATED",
            target=usuario,
            extra={
                "rolID": int(usuario.rolID),
                "sucursalID": int(usuario.sucursalID),
                "modulosAcceso": selected_user_modules,
            },
        )
        db.commit()
        db.refresh(usuario)

        return UserCreateResponse(
            status="ok",
            userID=int(usuario.idusuario),
            empresaID=int(usuario.empresaID),
            sucursalID=int(usuario.sucursalID),
            login=str(usuario.login),
            email=str(usuario.email),
            rolID=int(usuario.rolID),
            estado=str(usuario.estado),
            modulosAcceso=(selected_user_modules if payload.modulosAcceso is not None else None),
        )
    except SQLAlchemyError as exc:
        db.rollback()
        auth_logger.error("Error SQL creando usuario", exc_info=True)
        raise _err("AUTH_USER_CREATE_DB_ERROR", "Error interno del servidor", status_code=500)


@router.get("/usuarios", response_model=UserListResponse)
def listar_usuarios(
    empresa_id: int | None = Query(None, alias="empresaID"),
    sucursal_id: int | None = Query(None, alias="sucursalID"),
    estado: str | None = Query(None),
    q: str | None = Query(None),
    db: Session = Depends(get_db),
    auth=Depends(require_admin_role),
):
    query = (
        db.query(Usuario, Rol)
        .join(Rol, Rol.idRol == Usuario.rolID)
    )

    if not is_super_admin_context(auth):
        empresa_id = int(auth.empresaID)

    if empresa_id is not None:
        query = query.filter(Usuario.empresaID == empresa_id)
    if sucursal_id is not None:
        query = query.filter(Usuario.sucursalID == sucursal_id)
    if estado:
        query = query.filter(func.upper(Usuario.estado) == str(estado).strip().upper())
    else:
        query = query.filter(func.upper(Usuario.estado) != "ELIMINADO")
    if q:
        term = f"%{str(q).strip()}%"
        query = query.filter(
            Usuario.nombre.ilike(term)
            | Usuario.login.ilike(term)
            | Usuario.email.ilike(term)
        )

    rows = query.order_by(Usuario.empresaID.asc(), Usuario.sucursalID.asc(), Usuario.idusuario.desc()).all()
    items = [
        UserListItem(
            userID=int(usuario.idusuario),
            empresaID=int(usuario.empresaID),
            sucursalID=int(usuario.sucursalID),
            nombre=str(usuario.nombre or ""),
            login=str(usuario.login or ""),
            email=str(usuario.email or ""),
            rolID=int(usuario.rolID),
            rol=str(rol.nombreRol or ""),
            estado=str(usuario.estado or ""),
            ultimoLogin=usuario.ultimoLogin,
        )
        for usuario, rol in rows
    ]
    return UserListResponse(items=items, total=len(items))


@router.get("/usuarios/id/{user_id}", response_model=UserDetailResponse)
def obtener_usuario(
    user_id: int,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    if not is_empresa_admin_context(auth) and not is_super_admin_context(auth):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos para consultar usuarios")
    usuario, target_role = _get_target_user_for_admin(db, auth, user_id)
    rol_nombre = str(target_role.nombreRol or "") if target_role else ""
    return UserDetailResponse(
        userID=int(usuario.idusuario),
        empresaID=int(usuario.empresaID),
        sucursalID=int(usuario.sucursalID),
        nombre=str(usuario.nombre or ""),
        login=str(usuario.login or ""),
        email=str(usuario.email or ""),
        rolID=int(usuario.rolID),
        rol=rol_nombre,
        estado=str(usuario.estado or ""),
        modulosAcceso=_load_user_modules(db, int(usuario.idusuario), rol_nombre),
        ultimoLogin=usuario.ultimoLogin,
    )


@router.put("/usuarios/id/{user_id}", response_model=UserCreateResponse)
def actualizar_usuario(
    user_id: int,
    payload: UserUpdateRequest,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    try:
        if not is_empresa_admin_context(auth) and not is_super_admin_context(auth):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos para actualizar usuarios")

        usuario, _target_role = _get_target_user_for_admin(db, auth, user_id)
        _ensure_default_operational_roles(db, int(usuario.empresaID))

        login = payload.login.strip().lower()
        email = str(usuario.email or "").strip().lower() if payload.email is None else _user_email_or_default(payload.email, login, int(usuario.idusuario))
        estado = (payload.estado or "Activo").strip().title()
        if estado not in {"Activo", "Inactivo"}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="estado debe ser Activo o Inactivo")

        target_empresa_id = int(usuario.empresaID)

        existing_login = (
            db.query(Usuario)
            .filter(Usuario.login == login, Usuario.idusuario != int(usuario.idusuario))
            .first()
        )
        if existing_login:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Login ya existe")

        rol = (
            db.query(Rol)
            .filter(Rol.idRol == payload.rolID, Rol.empresaID == target_empresa_id)
            .first()
        )
        if not rol:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rol invalido para la empresa")

        role_name = normalize_role_name(rol.nombreRol)
        if not is_super_admin_context(auth) and role_name in STRUCTURAL_ROLES:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Empresa Admin no puede asignar roles estructurales")

        sucursal = db.query(Sucursal).filter(Sucursal.idSucursal == payload.sucursalID).first()
        if not sucursal:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Sucursal invalida")

        selected_user_modules = _validate_user_modules(db, target_empresa_id, payload.modulosAcceso)

        usuario.nombre = payload.nombre.strip()
        usuario.login = login
        usuario.email = email
        usuario.rolID = int(payload.rolID)
        usuario.sucursalID = int(payload.sucursalID)
        usuario.estado = estado
        if payload.password:
            usuario.passwordHash = pwd_context.hash(payload.password)
        usuario.updatedAt = datetime.now(timezone.utc)
        _sync_employee_profile_for_operational_user(db, usuario, str(rol.nombreRol or ""))

        if payload.modulosAcceso is not None:
            _ensure_usuario_modulo_table(db)
            db.execute(
                text("DELETE FROM petalops.usuario_modulo WHERE usuario_id = :user_id"),
                {"user_id": int(usuario.idusuario)},
            )
            for modulo in selected_user_modules:
                db.execute(
                    text(
                        """
                        INSERT INTO petalops.usuario_modulo (usuario_id, modulo, activo, updated_at)
                        VALUES (:user_id, :modulo, TRUE, CURRENT_TIMESTAMP)
                        """
                    ),
                    {"user_id": int(usuario.idusuario), "modulo": modulo},
                )

        _audit_user_action(
            db,
            actor=auth,
            action="USER_UPDATED",
            target=usuario,
            extra={
                "rolID": int(usuario.rolID),
                "sucursalID": int(usuario.sucursalID),
                "estado": estado,
                "modulosAcceso": selected_user_modules,
                "passwordUpdated": bool(payload.password),
            },
        )
        db.commit()
        db.refresh(usuario)

        return UserCreateResponse(
            status="ok",
            userID=int(usuario.idusuario),
            empresaID=int(usuario.empresaID),
            sucursalID=int(usuario.sucursalID),
            login=str(usuario.login),
            email=str(usuario.email),
            rolID=int(usuario.rolID),
            estado=str(usuario.estado),
            modulosAcceso=(selected_user_modules if payload.modulosAcceso is not None else None),
        )
    except SQLAlchemyError:
        db.rollback()
        auth_logger.error("Error SQL actualizando usuario", exc_info=True)
        raise _err("AUTH_USER_UPDATE_DB_ERROR", "Error interno del servidor", status_code=500)


@router.put("/usuarios/{user_id}/estado", response_model=UserCreateResponse)
def actualizar_estado_usuario(
    user_id: int,
    payload: UserStatusUpdateRequest,
    db: Session = Depends(get_db),
    auth=Depends(require_admin_role),
):
    usuario, _target_role = _get_target_user_for_admin(db, auth, user_id)

    estado = str(payload.estado or "").strip().title()
    if estado not in {"Activo", "Inactivo"}:
        raise HTTPException(status_code=400, detail="estado debe ser Activo o Inactivo")

    usuario.estado = estado
    usuario.updatedAt = datetime.now(timezone.utc)
    db.execute(
        text(
            """
            UPDATE petalops.empleado
            SET activo = :activo,
                updated_at = CURRENT_TIMESTAMP
            WHERE empresa_id = :empresa_id
              AND usuario_id = :usuario_id
            """
        ),
        {
            "activo": 1 if estado == "Activo" else 0,
            "empresa_id": int(usuario.empresaID),
            "usuario_id": int(usuario.idusuario),
        },
    )
    _audit_user_action(
        db,
        actor=auth,
        action="USER_STATUS_UPDATED",
        target=usuario,
        extra={"estado": estado},
    )
    db.commit()

    return UserCreateResponse(
        status="ok",
        userID=int(usuario.idusuario),
        empresaID=int(usuario.empresaID),
        sucursalID=int(usuario.sucursalID),
        login=str(usuario.login),
        email=str(usuario.email),
        rolID=int(usuario.rolID),
        estado=str(usuario.estado),
    )


@router.delete("/usuarios/id/{user_id}", response_model=UserDeleteResponse)
def eliminar_usuario(
    user_id: int,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    try:
        if not is_empresa_admin_context(auth) and not is_super_admin_context(auth):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos para eliminar usuarios")

        usuario, _target_role = _get_target_user_for_admin(db, auth, user_id)
        target_id = int(usuario.idusuario)
        if int(auth.userID) == target_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No puedes eliminar tu propio usuario")

        _ensure_usuario_modulo_table(db)
        db.execute(text("DELETE FROM petalops.usuario_modulo WHERE usuario_id = :user_id"), {"user_id": target_id})
        db.execute(
            text(
                """
                UPDATE petalops.empleado
                SET usuario_id = NULL,
                    activo = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE empresa_id = :empresa_id
                  AND usuario_id = :user_id
                """
            ),
            {"empresa_id": int(usuario.empresaID), "user_id": target_id},
        )
        _audit_user_action(
            db,
            actor=auth,
            action="USER_DELETED",
            target=usuario,
            extra={
                "login": str(usuario.login or ""),
                "email": str(usuario.email or ""),
                "rolID": int(usuario.rolID),
            },
        )
        db.delete(usuario)
        try:
            db.commit()
        except SQLAlchemyError:
            db.rollback()
            usuario, _target_role = _get_target_user_for_admin(db, auth, user_id)
            deleted_login = f"deleted_{target_id}_{str(usuario.login or '').strip()}"[:80]
            usuario.login = deleted_login
            usuario.email = f"{deleted_login}@deleted.local"
            usuario.estado = "Eliminado"
            usuario.updatedAt = datetime.now(timezone.utc)
            _ensure_usuario_modulo_table(db)
            db.execute(text("DELETE FROM petalops.usuario_modulo WHERE usuario_id = :user_id"), {"user_id": target_id})
            db.execute(
                text(
                    """
                    UPDATE petalops.empleado
                    SET usuario_id = NULL,
                        activo = 0,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE empresa_id = :empresa_id
                      AND usuario_id = :user_id
                    """
                ),
                {"empresa_id": int(usuario.empresaID), "user_id": target_id},
            )
            _audit_user_action(
                db,
                actor=auth,
                action="USER_SOFT_DELETED",
                target=usuario,
                extra={"login": str(usuario.login or ""), "reason": "hard_delete_blocked_by_references"},
            )
            db.commit()
        return UserDeleteResponse(status="ok", userID=target_id)
    except SQLAlchemyError:
        db.rollback()
        auth_logger.error("Error SQL eliminando usuario", exc_info=True)
        raise _err(
            "AUTH_USER_DELETE_DB_ERROR",
            "No fue posible eliminar el usuario. Revisa si tiene movimientos o referencias asociadas.",
            status_code=500,
        )


@router.get("/usuarios/tipos", response_model=RoleListResponse)
@router.get("/usuarios/roles", response_model=RoleListResponse)
def listar_roles(
    empresa_id: int = Query(..., alias="empresaID"),
    db: Session = Depends(get_db),
    auth=Depends(require_admin_role),
):
    if not is_super_admin_context(auth):
        empresa_id = int(auth.empresaID)

    _ensure_default_operational_roles(db, int(empresa_id))
    db.flush()
    db.commit()

    rows = db.query(Rol).filter(Rol.empresaID == empresa_id).order_by(Rol.nombreRol.asc()).all()
    if not is_super_admin_context(auth):
        rows = [row for row in rows if normalize_role_name(row.nombreRol) not in STRUCTURAL_ROLES]
    return RoleListResponse(
        items=[RoleOption(rolID=int(row.idRol), nombreRol=str(row.nombreRol or "")) for row in rows]
    )


@router.get("/usuarios/sucursales", response_model=SucursalListResponse)
def listar_sucursales(
    empresa_id: int = Query(..., alias="empresaID"),
    db: Session = Depends(get_db),
    auth=Depends(require_admin_role),
):
    if not is_super_admin_context(auth):
        empresa_id = int(auth.empresaID)

    rows = db.execute(
        text(
            """
            SELECT id_sucursal
            FROM petalops.sucursal
            WHERE empresa_id = :empresa_id
              AND id_sucursal IS NOT NULL
            ORDER BY id_sucursal ASC
            """
        ),
        {"empresa_id": empresa_id},
    ).all()

    items = [SucursalOption(sucursalID=int(row[0])) for row in rows]
    if not items:
        items = [SucursalOption(sucursalID=1)]
    return SucursalListResponse(items=items)


@router.get("/usuarios/empresas", response_model=EmpresaListResponse)
def listar_empresas(
    db: Session = Depends(get_db),
    auth=Depends(require_global_join_user),
):
    try:
        rows = db.execute(
            text(
                """
                SELECT id_empresa, COALESCE(nombre_comercial, nombre_empresa) AS nombre
                FROM petalops.empresa
                ORDER BY id_empresa ASC
                """
            )
        ).all()
    except SQLAlchemyError:
        db.rollback()
        rows = db.execute(
            text(
                """
                SELECT id_empresa, CONCAT('Empresa ', id_empresa) AS nombre
                FROM petalops.empresa
                ORDER BY id_empresa ASC
                """
            )
        ).all()

    return EmpresaListResponse(
        items=[
            EmpresaOption(empresaID=int(row[0]), nombre=str(row[1] or f"Empresa {int(row[0])}"))
            for row in rows
        ]
    )


@router.get("/usuarios/empresas/modulos", response_model=EmpresaModuloResumenResponse)
def listar_empresas_modulos(
    db: Session = Depends(get_db),
    _auth=Depends(require_global_join_user),
):
    try:
        rows = db.execute(
            text(
                """
                SELECT id_empresa,
                       COALESCE(nombre_comercial, nombre_empresa, CONCAT('Empresa ', id_empresa)) AS nombre,
                       plan_id,
                       estado
                FROM petalops.empresa
                ORDER BY id_empresa ASC
                """
            )
        ).all()
    except SQLAlchemyError:
        db.rollback()
        rows = db.execute(
            text(
                """
                SELECT id_empresa,
                       CONCAT('Empresa ', id_empresa) AS nombre,
                       NULL AS plan_id,
                       'Activo' AS "estado"
                FROM petalops.empresa
                ORDER BY id_empresa ASC
                """
            )
        ).all()

    items: list[EmpresaModuloResumenItem] = []
    for row in rows:
        empresa_id = int(row[0])
        try:
            modulos = _build_empresa_module_items(db, empresa_id)
        except Exception:
            db.rollback()  # â† limpia si falla una empresa
            modulos = []
        items.append(
            EmpresaModuloResumenItem(
                empresaID=empresa_id,
                nombre=str(row[1] or f"Empresa {empresa_id}"),
                planID=(int(row[2]) if row[2] is not None else None),
                estado=(str(row[3]) if row[3] is not None else None),
                items=modulos,
            )
        )
    return EmpresaModuloResumenResponse(items=items)


@router.post("/usuarios/empresas", response_model=EmpresaCreateResponse)
def crear_empresa(
    payload: EmpresaCreateRequest,
    db: Session = Depends(get_db),
    _auth=Depends(require_global_join_user),
):
    try:
        nombre = str(payload.nombreComercial or "").strip()
        if len(nombre) < 3:
            raise HTTPException(status_code=400, detail="nombreComercial debe tener al menos 3 caracteres")

        estado = str(payload.estado or "Activo").strip().title()
        if estado not in {"Activo", "Inactivo"}:
            raise HTTPException(status_code=400, detail="estado debe ser Activo o Inactivo")

        plan_id = int(payload.planID or 1)
        if plan_id < 1:
            raise HTTPException(status_code=400, detail="planID debe ser mayor o igual a 1")

        columns = _load_empresa_columns(db)
        if "id_empresa" not in columns:
            raise HTTPException(status_code=500, detail="Tabla empresa sin columna id_empresa")
        if "nombre_empresa" not in columns or "nit" not in columns:
            raise HTTPException(status_code=500, detail="Tabla empresa sin columnas obligatorias nombre_empresa/nit")

        next_id_row = db.execute(text("SELECT COALESCE(MAX(id_empresa), 0) + 1 FROM petalops.empresa")).first()
        next_empresa_id = int(next_id_row[0] if next_id_row and next_id_row[0] is not None else 1)
        nit = f"NIT-{next_empresa_id}"

        db.execute(
            text(
                """
                INSERT INTO petalops.empresa
                (id_empresa, nombre_empresa, nit, estado, nombre_comercial, plan_id, created_at, updated_at)
                VALUES
                (:id_empresa, :nombre_empresa, :nit, :estado, :nombre_comercial, :plan_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            ),
            {
                "id_empresa": next_empresa_id,
                "nombre_empresa": nombre,
                "nit": nit,
                "estado": 1 if estado == "Activo" else 0,
                "nombre_comercial": nombre,
                "plan_id": plan_id,
            },
        )

        # Sin esto el formulario de pedidos arranca sin ninguna opcion de
        # metodo de pago para la empresa nueva hasta que un admin agregue la
        # primera a mano desde /configuracion (ver empresa 2 en produccion).
        db.execute(
            text(
                """
                INSERT INTO petalops.metodo_pago_catalogo (
                    empresa_id, codigo, nombre, orden, activo, created_at, updated_at
                ) VALUES (
                    :empresa_id, 'efectivo', 'Efectivo', 1, TRUE, NOW(), NOW()
                )
                """
            ),
            {"empresa_id": next_empresa_id},
        )
        sync_empresa_menu_opciones(db, empresa_id=next_empresa_id, campo="pedido_metodos_pago")

        db.execute(
            text(
                """
                INSERT INTO petalops.canal_venta (
                    empresa_id, codigo, nombre, orden, activo, created_at, updated_at
                ) VALUES (
                    :empresa_id, 'presencial', 'Presencial', 1, TRUE, NOW(), NOW()
                )
                """
            ),
            {"empresa_id": next_empresa_id},
        )
        sync_empresa_menu_opciones(db, empresa_id=next_empresa_id, campo="pedido_canal_venta")

        db.commit()

        return EmpresaCreateResponse(
            status="ok",
            empresaID=next_empresa_id,
            nombre=nombre,
            planID=plan_id,
            estado=estado,
        )
    except SQLAlchemyError as exc:
        db.rollback()
        auth_logger.error("Error SQL creando empresa", exc_info=True)
        raise _err("AUTH_EMPRESA_CREATE_DB_ERROR", "Error interno del servidor", status_code=500)


@router.get("/usuarios/modulos", response_model=EmpresaModuloListResponse)
def listar_modulos_empresa(
    request: Request,
    empresa_id: int = Query(..., alias="empresaID"),
    db: Session = Depends(get_db),
    auth=Depends(require_admin_role),
):
    try:
        if not is_super_admin_context(auth):
            empresa_id = int(auth.empresaID)
        normalized_empresa_id = _resolve_empresa_id_for_module_admin(db, empresa_id)
        _ensure_default_operational_roles(db, normalized_empresa_id)

        cache_key = f"empresa_config:{normalized_empresa_id}"
        cached = get_cache(cache_key)
        if cached is not None:
            return EmpresaModuloListResponse(**cached)

        _ensure_empresa_modulo_table(db)
        items = _build_empresa_module_items(db, normalized_empresa_id)
        response = EmpresaModuloListResponse(empresaID=normalized_empresa_id, items=items)
        set_cache(cache_key, response.model_dump(), ttl=300)
        return response
    except SQLAlchemyError as exc:
        auth_logger.error("Error SQL listando modulos de empresa", exc_info=True)
        raise _err("AUTH_EMPRESA_MODULOS_DB_ERROR", "Error interno del servidor", status_code=500)

@router.put("/usuarios/modulos", response_model=EmpresaModuloUpdateResponse)
def actualizar_modulos_empresa(
    payload: EmpresaModuloUpdateRequest,
    db: Session = Depends(get_db),
    _auth=Depends(require_global_join_user),
):
    try:
        empresa_id = _resolve_empresa_id_for_module_admin(db, int(payload.empresaID))
        _ensure_empresa_modulo_table(db)
        normalized_items = []
        for item in payload.items:
            modulo = normalize_module_name(item.modulo)
            if not modulo:
                continue
            normalized_items.append((modulo, bool(item.activo)))

        # Replace current configuration for this company.
        db.execute(
            text("DELETE FROM petalops.empresa_modulo WHERE empresa_id = :empresa_id"),
            {"empresa_id": empresa_id},
        )
        for modulo, activo in normalized_items:
            db.execute(
                text("INSERT INTO petalops.empresa_modulo (empresa_id, modulo, activo, updatedat) VALUES (:empresa_id, :modulo, :activo, CURRENT_TIMESTAMP)"),
                {
                    "empresa_id": empresa_id,
                    "modulo": modulo,
                    "activo": bool(activo),
                },
            )

        db.commit()

        # Refresh cache snapshot after mutation to keep reads consistent.
        updated_items = _build_empresa_module_items(db, empresa_id)
        set_cache(
            f"empresa_config:{empresa_id}",
            EmpresaModuloListResponse(empresaID=empresa_id, items=updated_items).model_dump(),
            ttl=300,
        )

        return EmpresaModuloUpdateResponse(
            status="ok",
            empresaID=empresa_id,
            updated=len(normalized_items),
        )
    except SQLAlchemyError as exc:
        db.rollback()
        auth_logger.error("Error SQL actualizando modulos de empresa", exc_info=True)
        raise _err("AUTH_EMPRESA_MODULOS_UPDATE_DB_ERROR", "Error interno del servidor", status_code=500)


