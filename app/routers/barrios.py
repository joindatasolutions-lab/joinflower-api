from fastapi import APIRouter, Depends, Query
from sqlalchemy import String, cast, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.barrio import Barrio
from app.core.security import assert_same_empresa, get_current_auth_context, require_module_access
from app.services.cache import get_cache, set_cache

router = APIRouter()


def _activo_truthy(column):
    return func.lower(cast(column, String)).in_(["true", "t", "1"])


@router.get("/barrios/search", dependencies=[Depends(require_module_access("pedidos", "puedeVer"))])
def search_barrios(
    q: str = Query(default=""),
    empresa_id: int = Query(...),
    sucursal_id: int = Query(...),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)
    texto = q.strip()
    modo_base = len(texto) < 2

    cache_key = f"barrios:v2:{empresa_id}:{sucursal_id}:{texto.lower() or '__base__'}"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached

    query = (
        db.query(Barrio)
        .filter(
            _activo_truthy(Barrio.activo),
            Barrio.empresaID == empresa_id,
            Barrio.sucursalID == sucursal_id,
        )
    )

    if not modo_base:
        query = query.filter(Barrio.nombreBarrio.ilike(f"%{texto}%"))

    barrios = (
        query
        .order_by(Barrio.nombreBarrio.asc())
        .limit(500 if modo_base else 25)
        .all()
    )

    response = [
        {
            "idBarrio": barrio.idBarrio,
            "nombreBarrio": barrio.nombreBarrio,
            "costoDomicilio": float(barrio.costoDomicilio),
        }
        for barrio in barrios
    ]

    if modo_base:
        response.sort(
            key=lambda item: (
                0 if str(item.get("nombreBarrio", "")).strip().lower() == "recoger en tienda" else 1,
                str(item.get("nombreBarrio", "")).lower(),
            )
        )

    # Neighborhood lookups are frequently repeated by destination autocomplete.
    set_cache(cache_key, response, ttl=3600)
    return response
