from __future__ import annotations

from pydantic import BaseModel, Field


class CatalogoItem(BaseModel):
    id: int
    codigo: str
    nombre: str
    orden: int
    activo: bool
    cuenta: str | None = None
    numeroCuenta: str | None = None
    activasCuentasCatalogo: bool | None = None


class CatalogoListResponse(BaseModel):
    items: list[CatalogoItem]
    datosTransferenciaCatalogoActivo: bool | None = None


class CatalogoCreateRequest(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    cuenta: str | None = Field(default=None, max_length=120)
    numeroCuenta: str | None = Field(default=None, max_length=80)
    activasCuentasCatalogo: bool | None = None


class CatalogoUpdateRequest(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=120)
    orden: int | None = None
    activo: bool | None = None
    cuenta: str | None = Field(default=None, max_length=120)
    numeroCuenta: str | None = Field(default=None, max_length=80)
    activasCuentasCatalogo: bool | None = None


class MenuCampoItem(BaseModel):
    codigo: str
    titulo: str
    tipoControl: str
    requeridoAprobacion: bool
    activo: bool
    orden: int
    totalOpciones: int


class MenuCampoListResponse(BaseModel):
    items: list[MenuCampoItem]


class MenuCampoUpdateRequest(BaseModel):
    titulo: str | None = Field(default=None, min_length=1, max_length=120)
    requeridoAprobacion: bool | None = None
    activo: bool | None = None


class ConfiguracionAsignacionResponse(BaseModel):
    empresaID: int
    asignacionProduccionActiva: bool
    asignacionDomicilioActiva: bool
    autoAsignacionProduccionActiva: bool


class ConfiguracionAsignacionUpdateRequest(BaseModel):
    asignacionProduccionActiva: bool | None = None
    asignacionDomicilioActiva: bool | None = None
    autoAsignacionProduccionActiva: bool | None = None


class ConfiguracionCatalogoTransferenciaResponse(BaseModel):
    empresaID: int
    datosTransferenciaCatalogoActivo: bool


class ConfiguracionCatalogoTransferenciaUpdateRequest(BaseModel):
    datosTransferenciaCatalogoActivo: bool
