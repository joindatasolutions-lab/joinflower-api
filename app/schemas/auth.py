import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class LoginRequest(BaseModel):
    login: str = Field(min_length=3)
    password: str = Field(min_length=3)


class PermisoModuloItem(BaseModel):
    modulo: str
    puedeVer: bool
    puedeCrear: bool
    puedeEditar: bool
    puedeEliminar: bool


class RoleAssignmentItem(BaseModel):
    rolID: int
    nombreRol: str
    principal: bool = False


class AuthMeResponse(BaseModel):
    userID: int
    empresaID: int
    empresaNombre: str | None = None
    empresaSlug: str | None = None
    sucursalID: int | None = None
    planID: int | None = None
    rolID: int
    rol: str
    roles: list[RoleAssignmentItem] = Field(default_factory=list)
    nombre: str
    login: str
    email: str
    esGlobalJoin: bool = False
    ultimoLogin: datetime | None = None
    permisos: list[PermisoModuloItem]
    modulosActivosPlan: list[str]


class LoginResponse(BaseModel):
    accessToken: str
    tokenType: str = "bearer"
    expiresIn: int
    user: AuthMeResponse


class AdminProductosSessionResponse(BaseModel):
    url: str


class ImpersonateRequest(BaseModel):
    empresaID: int
    sucursalID: int | None = None


class TokenPayload(BaseModel):
    userID: int
    empresaID: int
    rolID: int
    planID: int | None = None
    exp: int
    iat: int


class AuthContext(BaseModel):
    userID: int
    empresaID: int
    empresaNombre: str | None = None
    empresaSlug: str | None = None
    sucursalID: int | None = None
    rolID: int
    planID: int | None = None
    rol: str
    roles: list[RoleAssignmentItem] = Field(default_factory=list)
    nombre: str
    login: str
    email: str
    esGlobalJoin: bool = False
    ultimoLogin: datetime | None = None
    permisos: dict[str, dict[str, bool]]
    modulosActivosPlan: set[str]

    def can(self, modulo: str, accion: str) -> bool:
        permisos_modulo = self.permisos.get(modulo.lower()) or {}
        return bool(permisos_modulo.get(accion, False))

    def to_me_response(self) -> dict[str, Any]:
        permisos = []
        for modulo, data in sorted(self.permisos.items(), key=lambda item: item[0]):
            permisos.append(
                {
                    "modulo": modulo,
                    "puedeVer": bool(data.get("puedeVer", False)),
                    "puedeCrear": bool(data.get("puedeCrear", False)),
                    "puedeEditar": bool(data.get("puedeEditar", False)),
                    "puedeEliminar": bool(data.get("puedeEliminar", False)),
                }
            )

        return {
            "userID": self.userID,
            "empresaID": self.empresaID,
            "empresaNombre": self.empresaNombre,
            "empresaSlug": self.empresaSlug,
            "sucursalID": self.sucursalID,
            "planID": self.planID,
            "rolID": self.rolID,
            "rol": self.rol,
            "roles": self.roles,
            "nombre": self.nombre,
            "login": self.login,
            "email": self.email,
            "esGlobalJoin": self.esGlobalJoin,
            "ultimoLogin": self.ultimoLogin,
            "permisos": permisos,
            "modulosActivosPlan": sorted(self.modulosActivosPlan),
        }


class UserCreateRequest(BaseModel):
    empresaID: int | None = None
    nombre: str = Field(min_length=3)
    login: str = Field(min_length=3)
    password: str = Field(min_length=6)
    email: str | None = None
    rolID: int
    sucursalID: int
    estado: str | None = "Activo"
    modulosAcceso: list[str] | None = None
    rolesIDs: list[int] | None = None


class UserCreateResponse(BaseModel):
    status: str
    userID: int
    empresaID: int
    sucursalID: int
    login: str
    email: str
    rolID: int
    rolesIDs: list[int] = Field(default_factory=list)
    roles: list[RoleAssignmentItem] = Field(default_factory=list)
    estado: str
    modulosAcceso: list[str] | None = None


class UserListItem(BaseModel):
    userID: int
    empresaID: int
    sucursalID: int
    nombre: str
    login: str
    email: str
    rolID: int
    rol: str
    rolesIDs: list[int] = Field(default_factory=list)
    roles: list[RoleAssignmentItem] = Field(default_factory=list)
    estado: str
    ultimoLogin: datetime | None = None


class UserListResponse(BaseModel):
    items: list[UserListItem]
    total: int


class UserStatusUpdateRequest(BaseModel):
    estado: str


class UserDetailResponse(BaseModel):
    userID: int
    empresaID: int
    sucursalID: int
    nombre: str
    login: str
    email: str
    rolID: int
    rol: str
    rolesIDs: list[int] = Field(default_factory=list)
    roles: list[RoleAssignmentItem] = Field(default_factory=list)
    estado: str
    modulosAcceso: list[str]
    ultimoLogin: datetime | None = None


class UserPasswordVaultResponse(BaseModel):
    available: bool
    password: str | None = None
    message: str | None = None


class UserUpdateRequest(BaseModel):
    nombre: str = Field(min_length=3)
    login: str = Field(min_length=3)
    email: str | None = None
    password: str | None = Field(default=None, min_length=6)
    rolID: int
    sucursalID: int
    estado: str | None = "Activo"
    modulosAcceso: list[str] | None = None
    rolesIDs: list[int] | None = None


class UserDeleteResponse(BaseModel):
    status: str
    userID: int


class RoleOption(BaseModel):
    rolID: int
    nombreRol: str
    modulosPermitidos: list[str] = []


class RoleListResponse(BaseModel):
    items: list[RoleOption]


class SucursalOption(BaseModel):
    sucursalID: int


class SucursalListResponse(BaseModel):
    items: list[SucursalOption]


class EmpresaOption(BaseModel):
    empresaID: int
    nombre: str
    empresaSlug: str | None = None


class EmpresaListResponse(BaseModel):
    items: list[EmpresaOption]


class EmpresaCreateRequest(BaseModel):
    nombreComercial: str = Field(min_length=3, max_length=180)
    planID: int = 1
    estado: str = "Activo"
    slug: str | None = Field(default=None, min_length=3, max_length=80)
    adminLogin: str | None = Field(default=None, min_length=3, max_length=80)
    adminPassword: str | None = Field(default=None, min_length=6, max_length=120)
    adminEmail: str | None = None
    sucursalNombre: str | None = Field(default=None, min_length=3, max_length=120)
    # Datos comerciales/de contacto de la empresa -- todos opcionales, se pueden completar
    # despues via PUT /usuarios/empresas/{id}. nit permite reemplazar el autogenerado.
    nit: str | None = Field(default=None, max_length=30)
    celular: str | None = Field(default=None, max_length=40)
    ciudad: str | None = Field(default=None, max_length=100)
    direccion: str | None = Field(default=None, max_length=255)
    nombreResponsable: str | None = Field(default=None, max_length=150)
    cargoResponsable: str | None = Field(default=None, max_length=100)
    correoResponsable: str | None = Field(default=None, max_length=150)
    celularResponsable: str | None = Field(default=None, max_length=30)

    @field_validator(
        "slug", "adminLogin", "adminPassword", "adminEmail", "sucursalNombre",
        "nit", "celular", "ciudad", "direccion", "nombreResponsable",
        "cargoResponsable", "correoResponsable", "celularResponsable",
        mode="before",
    )
    @classmethod
    def empty_optional_strings_to_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value


class EmpresaCreateResponse(BaseModel):
    status: str
    empresaID: int
    nombre: str
    planID: int
    estado: str
    sucursalID: int | None = None
    adminUserID: int | None = None
    assetsPrefix: str | None = None


class EmpresaAssetsProvisionResponse(BaseModel):
    status: str
    empresaID: int
    empresaSlug: str
    assetsPrefix: str
    createdKeys: list[str] = Field(default_factory=list)


class EmpresaDetailResponse(BaseModel):
    empresaID: int
    nombreComercial: str
    nombreEmpresa: str
    nit: str | None = None
    estado: str
    slug: str | None = None
    dominio: str | None = None
    logoUrl: str | None = None
    planID: int | None = None
    celular: str | None = None
    ciudad: str | None = None
    direccion: str | None = None
    nombreResponsable: str | None = None
    cargoResponsable: str | None = None
    correoResponsable: str | None = None
    celularResponsable: str | None = None


class EmpresaUpdateRequest(BaseModel):
    nombreComercial: str | None = Field(default=None, min_length=3, max_length=180)
    estado: str | None = None
    nit: str | None = Field(default=None, max_length=30)
    celular: str | None = Field(default=None, max_length=40)
    ciudad: str | None = Field(default=None, max_length=100)
    direccion: str | None = Field(default=None, max_length=255)
    nombreResponsable: str | None = Field(default=None, max_length=150)
    cargoResponsable: str | None = Field(default=None, max_length=100)
    correoResponsable: str | None = Field(default=None, max_length=150)
    celularResponsable: str | None = Field(default=None, max_length=30)

    @field_validator(
        "nit", "celular", "ciudad", "direccion", "nombreResponsable",
        "cargoResponsable", "correoResponsable", "celularResponsable",
        mode="before",
    )
    @classmethod
    def empty_optional_strings_to_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value


class EmpresaUpdateResponse(BaseModel):
    status: str
    empresaID: int


# Solo se exponen los campos que el panel de superusuario realmente edita hoy
# (color primario, color secundario y tipo de letra) -- la tabla tema tiene mas
# columnas (fondo, texto, bordes) reservadas para una fase futura.
class TemaResponse(BaseModel):
    empresaID: int
    colorPrimario: str | None = None
    colorSecundario: str | None = None
    fuenteFamilia: str | None = None


class TemaUpdateRequest(BaseModel):
    colorPrimario: str = Field(min_length=4, max_length=20)
    colorSecundario: str = Field(min_length=4, max_length=20)
    fuenteFamilia: str = Field(min_length=3, max_length=255)

    @field_validator("colorPrimario", "colorSecundario")
    @classmethod
    def validar_color_hex(cls, value: str) -> str:
        value = value.strip()
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            raise ValueError("El color debe ser un hexadecimal valido, ej. #3A554D")
        return value


class EmpresaModuloItem(BaseModel):
    modulo: str
    activo: bool


class EmpresaModuloListResponse(BaseModel):
    empresaID: int
    items: list[EmpresaModuloItem]


class EmpresaModuloResumenItem(BaseModel):
    empresaID: int
    nombre: str
    empresaSlug: str | None = None
    planID: int | None = None
    estado: str | None = None
    items: list[EmpresaModuloItem]


class EmpresaModuloResumenResponse(BaseModel):
    items: list[EmpresaModuloResumenItem]


class EmpresaModuloUpdateRequest(BaseModel):
    empresaID: int
    items: list[EmpresaModuloItem]


class EmpresaModuloUpdateResponse(BaseModel):
    status: str
    empresaID: int
    updated: int
