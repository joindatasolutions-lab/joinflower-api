from datetime import datetime, timezone
import json
import os

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.security import (
    JWT_EXPIRE_MINUTES,
    auth_schema_error,
    create_access_token,
    get_current_auth_context,
    load_empresa_auth_meta,
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
from app.models.rol import Rol
from app.models.sucursal import Sucursal
from app.models.usuario import Usuario
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
    RoleListResponse,
    RoleOption,
    SucursalListResponse,
    SucursalOption,
    UserCreateRequest,
    UserCreateResponse,
    UserListItem,
    UserListResponse,
    UserStatusUpdateRequest,
)

router = APIRouter(prefix="/auth", tags=["Auth"])


STRUCTURAL_ROLES = {"super_admin", "join_superadmin", "empresa_admin", "admin"}
DEFAULT_MODULES = {"pedidos", "produccion", "domicilios", "catalogo", "usuarios", "inventario"}

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


def _ensure_empresa_modulo_table(db: Session):
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS EmpresaModulo (
              empresaID BIGINT NOT NULL,
              modulo VARCHAR(80) NOT NULL,
              activo TINYINT(1) NOT NULL DEFAULT 1,
              updatedAt DATETIME NOT NULL,
              PRIMARY KEY (empresaID, modulo),
              INDEX idx_empresa_modulo_activo (empresaID, activo),
              CONSTRAINT fk_empresamodulo_empresa FOREIGN KEY (empresaID) REFERENCES Empresa(idEmpresa)
            )
            """
        )
    )


def _ensure_usuario_modulo_table(db: Session):
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS UsuarioModulo (
              userID BIGINT NOT NULL,
              modulo VARCHAR(80) NOT NULL,
              activo TINYINT(1) NOT NULL DEFAULT 1,
              updatedAt DATETIME NOT NULL,
              PRIMARY KEY (userID, modulo),
              INDEX idx_usuariomodulo_activo (userID, activo),
              CONSTRAINT fk_usuariomodulo_usuario FOREIGN KEY (userID) REFERENCES Usuario(idUsuario)
            )
            """
        )
    )


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
    db.execute(
        text(
            """
            INSERT INTO UsuarioAuditoria (
              empresaID,
              actorUserID,
              actorLogin,
              accion,
              targetUserID,
              targetLogin,
              detalleJSON,
              createdAt
            )
            VALUES (
              :empresa_id,
              :actor_user_id,
              :actor_login,
              :accion,
              :target_user_id,
              :target_login,
              :detalle,
              NOW()
            )
            """
        ),
        {
            "empresa_id": int(target.empresaID),
            "actor_user_id": int(actor.userID),
            "actor_login": str(actor.login),
            "accion": action,
            "target_user_id": int(target.idUsuario),
            "target_login": str(target.login),
            "detalle": payload,
        },
    )


def _resolve_empresa_id_for_module_admin(db: Session, empresa_id: int) -> int:
    row = db.execute(
        text("SELECT idEmpresa FROM Empresa WHERE idEmpresa = :empresa_id LIMIT 1"),
        {"empresa_id": int(empresa_id)},
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    return int(row[0])


def _load_empresa_columns(db: Session) -> set[str]:
    rows = db.execute(
        text(
            """
            SELECT COLUMN_NAME
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'Empresa'
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
                text("SELECT modulo, activo FROM PlanModulo WHERE planID = :plan_id"),
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
                FROM PermisoModulo pm
                JOIN Rol r ON r.idRol = pm.rolID
                WHERE r.empresaID = :empresa_id
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
        text("SELECT modulo, activo FROM EmpresaModulo WHERE empresaID = :empresa_id"),
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
                text("SELECT modulo FROM PlanModulo WHERE planID = :plan_id AND activo = 1"),
                {"plan_id": int(effective_plan_id)},
            ).all()
            active_from_plan = {normalize_module_name(modulo) for (modulo,) in active_rows}
        except SQLAlchemyError:
            active_rows = []

    if not has_plan_rows and not overrides:
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


def _ensure_default_operational_roles(db: Session, empresa_id: int):
    for role_name, module_policy in DEFAULT_ROLE_MODULE_POLICY.items():
        db.execute(
            text(
                """
                INSERT INTO Rol (empresaID, nombreRol)
                VALUES (:empresa_id, :nombre_rol)
                ON DUPLICATE KEY UPDATE nombreRol = VALUES(nombreRol)
                """
            ),
            {"empresa_id": int(empresa_id), "nombre_rol": role_name},
        )

        role_row = db.execute(
            text(
                """
                SELECT idRol
                FROM Rol
                WHERE empresaID = :empresa_id AND nombreRol = :nombre_rol
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
                    "rol_id": role_id,
                    "modulo": normalize_module_name(modulo),
                    "puede_ver": int(bool(puede_ver)),
                    "puede_crear": int(bool(puede_crear)),
                    "puede_editar": int(bool(puede_editar)),
                    "puede_eliminar": int(bool(puede_eliminar)),
                },
            )


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    try:
        usuario = (
            db.query(Usuario)
            .filter(
                Usuario.login == payload.login.strip().lower(),
                Usuario.estado == "Activo",
            )
            .first()
        )
        if not usuario:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas")

        empresa_meta = load_empresa_auth_meta(db, int(usuario.empresaID))
        if not empresa_meta["exists"]:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas")

        if not is_empresa_activa(empresa_meta.get("estado")):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Empresa suspendida o inactiva")

        if str(usuario.estado or "").strip().upper() != "ACTIVO":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuario inactivo")

        if not verify_password(payload.password, str(usuario.passwordHash or "")):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas")

        rol = (
            db.query(Rol)
            .filter(Rol.idRol == usuario.rolID, Rol.empresaID == usuario.empresaID)
            .first()
        )
        if not rol:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Rol inválido para la empresa")

        usuario.ultimoLogin = datetime.now(timezone.utc)
        usuario.updatedAt = datetime.now(timezone.utc)
        db.commit()

        token = create_access_token(
            user_id=int(usuario.idUsuario),
            empresa_id=int(usuario.empresaID),
            sucursal_id=(int(usuario.sucursalID) if usuario.sucursalID is not None else None),
            rol_id=int(usuario.rolID),
            plan_id=empresa_meta["planID"],
        )

        auth_context = get_current_auth_context(token=token, db=db)

        return LoginResponse(
            accessToken=token,
            expiresIn=JWT_EXPIRE_MINUTES * 60,
            user=AuthMeResponse(**auth_context.to_me_response()),
        )
    except SQLAlchemyError as exc:
        raise auth_schema_error() from exc


@router.get("/me", response_model=AuthMeResponse)
def me(auth=Depends(get_current_auth_context)):
    return AuthMeResponse(**auth.to_me_response())


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

        login = payload.login.strip().lower()
        email = payload.email.strip().lower()
        estado = (payload.estado or "Activo").strip().title()
        if estado not in {"Activo", "Inactivo"}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="estado debe ser Activo o Inactivo")

        existing_login = db.query(Usuario).filter(Usuario.login == login).first()
        if existing_login:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Login ya existe")

        existing_email = (
            db.query(Usuario)
            .filter(Usuario.empresaID == target_empresa_id, Usuario.email == email)
            .first()
        )
        if existing_email:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email ya existe en la empresa")

        rol = (
            db.query(Rol)
            .filter(Rol.idRol == payload.rolID, Rol.empresaID == target_empresa_id)
            .first()
        )
        if not rol:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rol inválido para la empresa")

        role_name = normalize_role_name(rol.nombreRol)
        if not is_super_admin_context(auth) and role_name in STRUCTURAL_ROLES:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Empresa Admin no puede crear roles estructurales")

        empresa_meta = load_empresa_auth_meta(db, target_empresa_id)
        active_users = (
            db.query(func.count(Usuario.idUsuario))
            .filter(Usuario.empresaID == target_empresa_id, Usuario.estado == "Activo")
            .scalar()
        )
        max_users = _plan_user_limit(empresa_meta.get("planID"))
        if int(active_users or 0) >= max_users:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Límite de usuarios alcanzado para el plan ({max_users})")

        sucursal = db.query(Sucursal).filter(Sucursal.idSucursal == payload.sucursalID).first()
        if not sucursal:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Sucursal inválida")

        available_modules = {
            item.modulo
            for item in _build_empresa_module_items(db, target_empresa_id)
            if bool(item.activo)
        }
        requested_user_modules = _normalize_module_list(payload.modulosAcceso)
        selected_user_modules = [module for module in requested_user_modules if module in available_modules]

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
        if payload.modulosAcceso is not None:
            _ensure_usuario_modulo_table(db)
            db.execute(
                text("DELETE FROM UsuarioModulo WHERE userID = :user_id"),
                {"user_id": int(usuario.idUsuario)},
            )
            for modulo in selected_user_modules:
                db.execute(
                    text(
                        """
                        INSERT INTO UsuarioModulo (userID, modulo, activo, updatedAt)
                        VALUES (:user_id, :modulo, 1, NOW())
                        """
                    ),
                    {"user_id": int(usuario.idUsuario), "modulo": modulo},
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
            userID=int(usuario.idUsuario),
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
        raise auth_schema_error() from exc


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
    if q:
        term = f"%{str(q).strip()}%"
        query = query.filter(
            Usuario.nombre.like(term)
            | Usuario.login.like(term)
            | Usuario.email.like(term)
        )

    rows = query.order_by(Usuario.empresaID.asc(), Usuario.sucursalID.asc(), Usuario.idUsuario.desc()).all()
    items = [
        UserListItem(
            userID=int(usuario.idUsuario),
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


@router.put("/usuarios/{user_id}/estado", response_model=UserCreateResponse)
def actualizar_estado_usuario(
    user_id: int,
    payload: UserStatusUpdateRequest,
    db: Session = Depends(get_db),
    auth=Depends(require_admin_role),
):
    usuario = db.query(Usuario).filter(Usuario.idUsuario == user_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    if not is_super_admin_context(auth) and int(usuario.empresaID) != int(auth.empresaID):
        raise HTTPException(status_code=403, detail="No puedes modificar usuarios de otra empresa")

    target_role = db.query(Rol).filter(Rol.idRol == usuario.rolID).first()
    if target_role:
        target_role_name = normalize_role_name(target_role.nombreRol)
        if not is_super_admin_context(auth) and target_role_name in STRUCTURAL_ROLES:
            raise HTTPException(status_code=403, detail="No puedes modificar usuarios de rol estructural")

    estado = str(payload.estado or "").strip().title()
    if estado not in {"Activo", "Inactivo"}:
        raise HTTPException(status_code=400, detail="estado debe ser Activo o Inactivo")

    usuario.estado = estado
    usuario.updatedAt = datetime.now(timezone.utc)
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
        userID=int(usuario.idUsuario),
        empresaID=int(usuario.empresaID),
        sucursalID=int(usuario.sucursalID),
        login=str(usuario.login),
        email=str(usuario.email),
        rolID=int(usuario.rolID),
        estado=str(usuario.estado),
    )


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
            SELECT DISTINCT sucursalID
            FROM (
                SELECT sucursalID FROM Pedido WHERE empresaID = :empresa_id
                UNION ALL
                SELECT sucursalID FROM Produccion WHERE empresaID = :empresa_id
                UNION ALL
                SELECT sucursalID FROM Usuario WHERE empresaID = :empresa_id
            ) t
            WHERE sucursalID IS NOT NULL
            ORDER BY sucursalID ASC
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
                SELECT idEmpresa, COALESCE(nombreComercial, CONCAT('Empresa ', idEmpresa)) AS nombre
                FROM Empresa
                ORDER BY idEmpresa ASC
                """
            )
        ).all()
    except SQLAlchemyError:
        rows = db.execute(
            text(
                """
                SELECT idEmpresa, CONCAT('Empresa ', idEmpresa) AS nombre
                FROM Empresa
                ORDER BY idEmpresa ASC
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
                SELECT idEmpresa,
                       COALESCE(nombreComercial, CONCAT('Empresa ', idEmpresa)) AS nombre,
                       planID,
                       estado
                FROM Empresa
                ORDER BY idEmpresa ASC
                """
            )
        ).all()
    except SQLAlchemyError:
        rows = db.execute(
            text(
                """
                SELECT idEmpresa,
                       CONCAT('Empresa ', idEmpresa) AS nombre,
                       NULL AS planID,
                       'Activo' AS estado
                FROM Empresa
                ORDER BY idEmpresa ASC
                """
            )
        ).all()

    items: list[EmpresaModuloResumenItem] = []
    for row in rows:
        empresa_id = int(row[0])
        items.append(
            EmpresaModuloResumenItem(
                empresaID=empresa_id,
                nombre=str(row[1] or f"Empresa {empresa_id}"),
                planID=(int(row[2]) if row[2] is not None else None),
                estado=(str(row[3]) if row[3] is not None else None),
                items=_build_empresa_module_items(db, empresa_id),
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
        if "idEmpresa" not in columns:
            raise HTTPException(status_code=500, detail="Tabla Empresa sin columna idEmpresa")

        next_id_row = db.execute(text("SELECT COALESCE(MAX(idEmpresa), 0) + 1 FROM Empresa")).first()
        next_empresa_id = int(next_id_row[0] if next_id_row and next_id_row[0] is not None else 1)

        insert_fields = ["idEmpresa"]
        insert_params = [":id_empresa"]
        values = {"id_empresa": next_empresa_id}

        if "nombreComercial" in columns:
            insert_fields.append("nombreComercial")
            insert_params.append(":nombre")
            values["nombre"] = nombre

        if "planID" in columns:
            insert_fields.append("planID")
            insert_params.append(":plan_id")
            values["plan_id"] = plan_id

        if "estado" in columns:
            insert_fields.append("estado")
            insert_params.append(":estado")
            values["estado"] = estado

        db.execute(
            text(
                f"INSERT INTO Empresa ({', '.join(insert_fields)}) VALUES ({', '.join(insert_params)})"
            ),
            values,
        )
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
        raise auth_schema_error() from exc


@router.get("/usuarios/modulos", response_model=EmpresaModuloListResponse)
def listar_modulos_empresa(
    empresa_id: int = Query(..., alias="empresaID"),
    db: Session = Depends(get_db),
    auth=Depends(require_admin_role),
):
    try:
        if not is_super_admin_context(auth):
            empresa_id = int(auth.empresaID)
        normalized_empresa_id = _resolve_empresa_id_for_module_admin(db, empresa_id)
        _ensure_empresa_modulo_table(db)
        items = _build_empresa_module_items(db, normalized_empresa_id)
        return EmpresaModuloListResponse(empresaID=normalized_empresa_id, items=items)
    except SQLAlchemyError as exc:
        raise auth_schema_error() from exc


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
            text("DELETE FROM EmpresaModulo WHERE empresaID = :empresa_id"),
            {"empresa_id": empresa_id},
        )
        for modulo, activo in normalized_items:
            db.execute(
                text(
                    """
                    INSERT INTO EmpresaModulo (empresaID, modulo, activo, updatedAt)
                    VALUES (:empresa_id, :modulo, :activo, NOW())
                    """
                ),
                {
                    "empresa_id": empresa_id,
                    "modulo": modulo,
                    "activo": 1 if activo else 0,
                },
            )

        db.commit()
        return EmpresaModuloUpdateResponse(
            status="ok",
            empresaID=empresa_id,
            updated=len(normalized_items),
        )
    except SQLAlchemyError as exc:
        db.rollback()
        raise auth_schema_error() from exc
