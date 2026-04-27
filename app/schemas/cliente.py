from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class ClientePayload(BaseModel):
    empresaID: int = Field(alias="empresaID")
    tipoIdent: Optional[str] = None
    identificacion: Optional[str] = None
    indicativo: Optional[str] = None
    nombreCompleto: str = Field(min_length=2, max_length=150)
    telefono: Optional[str] = None
    telefonoCompleto: Optional[str] = None
    email: Optional[str] = None
    fechaCumpleanos: Optional[date] = None
    fechaAniversario: Optional[date] = None
    activo: bool = True


class ClienteUpdatePayload(BaseModel):
    empresaID: int = Field(alias="empresaID")
    tipoIdent: Optional[str] = None
    identificacion: Optional[str] = None
    indicativo: Optional[str] = None
    nombreCompleto: str = Field(min_length=2, max_length=150)
    telefono: Optional[str] = None
    telefonoCompleto: Optional[str] = None
    email: Optional[str] = None
    fechaCumpleanos: Optional[date] = None
    fechaAniversario: Optional[date] = None
    activo: bool = True
