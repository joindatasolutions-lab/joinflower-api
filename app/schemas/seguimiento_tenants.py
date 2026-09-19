from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class TenantSeguimientoItem(BaseModel):
    empresaID: int
    nombre: str
    slug: str | None = None
    logoUrl: str | None = None
    estado: str | None = None
    pedidosHoy: int = 0
    pedidosMes: int = 0
    tarifa: int = 0
    totalHoy: int = 0
    totalMes: int = 0


class TenantSeguimientoResumen(BaseModel):
    tenants: int = 0
    pedidosHoy: int = 0
    pedidosMes: int = 0
    totalHoy: int = 0
    totalMes: int = 0


class TenantSeguimientoResponse(BaseModel):
    fechaHoy: date
    mesDesde: date
    mesHasta: date
    resumen: TenantSeguimientoResumen
    items: list[TenantSeguimientoItem]
