from __future__ import annotations

from pydantic import BaseModel, Field


class CatalogoItem(BaseModel):
    id: int
    codigo: str
    nombre: str
    orden: int
    activo: bool


class CatalogoListResponse(BaseModel):
    items: list[CatalogoItem]


class CatalogoCreateRequest(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)


class CatalogoUpdateRequest(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=120)
    orden: int | None = None
    activo: bool | None = None


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
