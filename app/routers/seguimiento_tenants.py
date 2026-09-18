from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.security import get_current_auth_context, is_global_join_login
from app.core.timezone import colombia_today
from app.database import get_db
from app.schemas.seguimiento_tenants import (
    TenantSeguimientoItem,
    TenantSeguimientoResponse,
    TenantSeguimientoResumen,
)
from app.services.caja_service import column_exists

router = APIRouter(prefix="/seguimiento-tenants", tags=["Seguimiento Tenants"])


def _require_joinadmin_session(auth=Depends(get_current_auth_context)):
    if not bool(getattr(auth, "esGlobalJoin", False)) or not is_global_join_login(getattr(auth, "login", None)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo la sesion global de joinadmin puede acceder",
        )
    return auth


def _int(value) -> int:
    return int(value or 0)


def _str_or_none(value) -> str | None:
    if value is None:
        return None
    clean = str(value).strip()
    return clean or None


def _tenant_estado_expr(db: Session) -> str:
    if column_exists(db, "empresa", "estado"):
        return "e.estado"
    return "NULL"


def _tenant_logo_expr(db: Session) -> str:
    if column_exists(db, "empresa", "logo_url"):
        return "e.logo_url"
    return "NULL"


def _month_range(year: int, month: int) -> tuple[date, date]:
    start = date(int(year), int(month), 1)
    next_month = date(start.year + (1 if start.month == 12 else 0), 1 if start.month == 12 else start.month + 1, 1)
    return start, next_month - timedelta(days=1)


def _seguimiento_tenants_sql(db: Session) -> str:
    estado_expr = _tenant_estado_expr(db)
    logo_expr = _tenant_logo_expr(db)
    return f"""
        WITH pedidos AS (
            SELECT
                p.empresa_id,
                COUNT(*) FILTER (
                    WHERE CAST(p.fecha_pedido AS DATE) = :fecha_hoy
                      AND upper(COALESCE(ep.nombre_estado, '')) IN ('APROBADO', 'PAGADO')
                )::int AS pedidos_hoy,
                COUNT(*) FILTER (
                    WHERE CAST(p.fecha_pedido AS DATE) BETWEEN :mes_desde AND :mes_hasta
                      AND upper(COALESCE(ep.nombre_estado, '')) IN ('APROBADO', 'PAGADO')
                )::int AS pedidos_mes
            FROM petalops.pedido p
            LEFT JOIN petalops.estado_pedido ep
              ON ep.id_estado_pedido = p.estado_pedido_id
            GROUP BY p.empresa_id
        )
        SELECT
            e.id_empresa AS empresa_id,
            COALESCE(NULLIF(TRIM(e.nombre_comercial), ''), NULLIF(TRIM(e.nombre_empresa), ''), CONCAT('Empresa ', e.id_empresa)) AS nombre,
            e.slug,
            {logo_expr} AS logo_url,
            {estado_expr} AS estado,
            COALESCE(p.pedidos_hoy, 0) AS pedidos_hoy,
            COALESCE(p.pedidos_mes, 0) AS pedidos_mes
        FROM petalops.empresa e
        LEFT JOIN pedidos p ON p.empresa_id = e.id_empresa
        ORDER BY pedidos_mes DESC, pedidos_hoy DESC, e.id_empresa ASC
        LIMIT :limit
    """


def _row_to_tenant_item(row) -> TenantSeguimientoItem:
    return TenantSeguimientoItem(
        empresaID=int(row["empresa_id"]),
        nombre=str(row.get("nombre") or f"Empresa {row['empresa_id']}"),
        slug=_str_or_none(row.get("slug")),
        logoUrl=_str_or_none(row.get("logo_url")),
        estado=_str_or_none(row.get("estado")),
        pedidosHoy=_int(row.get("pedidos_hoy")),
        pedidosMes=_int(row.get("pedidos_mes")),
    )


def _build_resumen(items: list[TenantSeguimientoItem]) -> TenantSeguimientoResumen:
    return TenantSeguimientoResumen(
        tenants=len(items),
        pedidosHoy=sum(item.pedidosHoy for item in items),
        pedidosMes=sum(item.pedidosMes for item in items),
    )


@router.get(
    "/empresas",
    response_model=TenantSeguimientoResponse,
    dependencies=[Depends(_require_joinadmin_session)],
)
def obtener_seguimiento_tenants(
    anio: int | None = Query(None, alias="anio"),
    mes: int | None = Query(None, ge=1, le=12),
    fecha_hoy: date | None = Query(None, alias="fechaHoy"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    fecha_hoy = fecha_hoy or colombia_today()
    mes_desde, mes_hasta = _month_range(anio or fecha_hoy.year, mes or fecha_hoy.month)

    rows = db.execute(
        text(_seguimiento_tenants_sql(db)),
        {
            "fecha_hoy": fecha_hoy,
            "mes_desde": mes_desde,
            "mes_hasta": mes_hasta,
            "limit": int(limit),
        },
    ).mappings().all()
    items = [_row_to_tenant_item(row) for row in rows]
    return TenantSeguimientoResponse(
        fechaHoy=fecha_hoy,
        mesDesde=mes_desde,
        mesHasta=mes_hasta,
        resumen=_build_resumen(items),
        items=items,
    )
