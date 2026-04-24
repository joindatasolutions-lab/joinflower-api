from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import String, cast, func, or_, text
from sqlalchemy.orm import Session
from app.core.logger import get_logger
from app.database import get_db
from app.models.producto import Producto
from app.core.security import assert_same_empresa, get_current_auth_context
from app.services.cache import get_cache, set_cache

router = APIRouter()
catalogo_logger = get_logger("catalogo")


def _activo_truthy(column):
    return func.lower(cast(column, String)).in_(["true", "t", "1"])


def _err(code: str, message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "module": "catalogo"},
    )


@router.get("/catalogo/{empresa_id}")
def obtener_catalogo(
    empresa_id: int,
    sucursalId: int | None = Query(default=None),
    q: str | None = Query(default=None),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    try:
        assert_same_empresa(auth, empresa_id)
        if not (auth.can("catalogo", "puedeVer") or auth.can("pedidos", "puedeVer")):
            raise _err("CATALOGO_FORBIDDEN", "No tienes acceso al catálogo", status_code=403)

        target_sucursal_id = int(sucursalId if sucursalId is not None else (auth.sucursalID or 0))
        if target_sucursal_id <= 0:
            raise _err("CATALOGO_SUCURSAL_REQUIRED", "Sucursal inválida para consultar catálogo", status_code=400)

        term = str(q or "").strip()
        cache_key = (
            f"catalogo:{empresa_id}:sucursal:{target_sucursal_id}:{term.lower()}"
            if term else f"catalogo:{empresa_id}:sucursal:{target_sucursal_id}"
        )
        if not term:
            cached = get_cache(cache_key)
            if cached is not None:
                return cached

        params = {
            "empresa_id": int(empresa_id),
            "sucursal_id": target_sucursal_id,
        }
        term_filter = ""
        if term:
            params["term"] = f"%{term}%"
            term_filter = """
                AND (
                    p.nombre_producto ILIKE :term
                    OR COALESCE(p.descripcion, '') ILIKE :term
                    OR COALESCE(p.codigo_producto, '') ILIKE :term
                )
            """

        rows = db.execute(
            text(
                f"""
                SELECT
                    p.id_producto AS id_producto,
                    p.nombre_producto AS nombre_producto,
                    ps.precio AS precio,
                    ps.imagen_url AS imagen_url,
                    ps.es_destacado AS es_destacado,
                    ps.orden_catalogo AS orden_catalogo
                FROM petalops.producto p
                JOIN petalops.producto_sucursal ps
                  ON ps.producto_id = p.id_producto
                 AND ps.sucursal_id = :sucursal_id
                WHERE p.empresa_id = :empresa_id
                  AND lower(CAST(p.activo AS VARCHAR)) IN ('true', 't', '1')
                  AND lower(CAST(ps.activo AS VARCHAR)) IN ('true', 't', '1')
                  {term_filter}
                ORDER BY COALESCE(ps.es_destacado, false) DESC, ps.orden_catalogo ASC NULLS LAST, p.nombre_producto ASC
                """
            ),
            params,
        ).mappings().all()

        response = []
        for row in rows:
            response.append(
                {
                    "idProducto": int(row["id_producto"]),
                    "nombreProducto": row["nombre_producto"],
                    "precio": float(row["precio"] or 0),
                    "imagenUrl": row["imagen_url"],
                    "esDestacado": bool(row["es_destacado"]) if row["es_destacado"] is not None else False,
                    "ordenCatalogo": row["orden_catalogo"],
                    "nombreCategoria": None,
                }
            )

        if not term:
            # Product catalog is read-heavy and changes less frequently.
            set_cache(cache_key, response, ttl=600)
        return response
    except SQLAlchemyError:
        catalogo_logger.error("Error SQL al obtener catálogo. empresa_id=%s", empresa_id, exc_info=True)
        raise _err("CATALOGO_DB_ERROR", "Error interno del servidor", status_code=500)
