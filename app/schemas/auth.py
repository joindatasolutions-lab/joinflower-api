from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    login: str = Field(min_length=3)
    password: str = Field(min_length=3)


class PermisoModuloItem(BaseModel):
    modulo: str
    puedeVer: bool
    puedeCrear: bool
    puedeEditar: bool
    puedeEliminar: bool


class AuthMeResponse(BaseModel):
    userID: int
    empresaID: int
    sucursalID: int | None = None
    planID: int | None = None
    rolID: int
    rol: str
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
    sucursalID: int | None = None
    rolID: int
    planID: int | None = None
    rol: str
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
            "sucursalID": self.sucursalID,
            "planID": self.planID,
            "rolID": self.rolID,
            "rol": self.rol,
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
    email: str = Field(min_length=3)
    rolID: int
    sucursalID: int
    estado: str | None = "Activo"
    modulosAcceso: list[str] | None = None


class UserCreateResponse(BaseModel):
    status: str
    userID: int
    empresaID: int
    sucursalID: int
    login: str
    email: str
    rolID: int
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
    estado: str
    ultimoLogin: datetime | None = None


class UserListResponse(BaseModel):
    items: list[UserListItem]
    total: int


class UserStatusUpdateRequest(BaseModel):
    estado: str


class RoleOption(BaseModel):
    rolID: int
    nombreRol: str


class RoleListResponse(BaseModel):
    items: list[RoleOption]


class SucursalOption(BaseModel):
    sucursalID: int


class SucursalListResponse(BaseModel):
    items: list[SucursalOption]


class EmpresaOption(BaseModel):
    empresaID: int
    nombre: str


class EmpresaListResponse(BaseModel):
    items: list[EmpresaOption]


class EmpresaCreateRequest(BaseModel):
    nombreComercial: str = Field(min_length=3, max_length=180)
    planID: int = 1
    estado: str = "Activo"


class EmpresaCreateResponse(BaseModel):
    status: str
    empresaID: int
    nombre: str
    planID: int
    estado: str


class EmpresaModuloItem(BaseModel):
    modulo: str
    activo: bool


class EmpresaModuloListResponse(BaseModel):
    empresaID: int
    items: list[EmpresaModuloItem]


class EmpresaModuloResumenItem(BaseModel):
    empresaID: int
    nombre: str
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
