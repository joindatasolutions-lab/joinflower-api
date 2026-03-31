from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import String, cast, func
from sqlalchemy.orm import Session, joinedload
from app.core.logger import get_logger
from app.database import get_db
from app.models.producto import Producto
from app.core.security import assert_same_empresa, get_current_auth_context, require_module_access
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


@router.get("/catalogo/{empresa_id}", dependencies=[Depends(require_module_access("catalogo", "puedeVer"))])
def obtener_catalogo(empresa_id: int, db: Session = Depends(get_db), auth=Depends(get_current_auth_context)):
    try:
        assert_same_empresa(auth, empresa_id)

        cache_key = f"catalogo:{empresa_id}"
        cached = get_cache(cache_key)
        if cached is not None:
            return cached

        productos = (
            db.query(Producto)
            .options(joinedload(Producto.categoria))
            .filter(
                _activo_truthy(Producto.activo),
                Producto.empresaID == empresa_id
            )
            .order_by(Producto.nombreProducto.asc())
            .all()
        )

        response = [
            {
                "idProducto": p.idProducto,
                "nombreProducto": p.nombreProducto,
                "precio": float(getattr(p, "precioBase", 0) or 0),
                "imagenUrl": getattr(p, "imagenUrl", None),
                "esDestacado": False,
                "ordenCatalogo": None,
                "nombreCategoria": p.categoria.nombreCategoria if p.categoria else None
            }
            for p in productos
        ]

        # Product catalog is read-heavy and changes less frequently.
        set_cache(cache_key, response, ttl=600)
        return response
    except SQLAlchemyError:
        catalogo_logger.error("Error SQL al obtener catálogo. empresa_id=%s", empresa_id, exc_info=True)
        raise _err("CATALOGO_DB_ERROR", "Error interno del servidor", status_code=500)
