from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.models.producto import Producto
from app.core.security import assert_same_empresa, get_current_auth_context, require_module_access
from app.services.cache import get_cache, set_cache

router = APIRouter()


@router.get("/catalogo/{empresa_id}", dependencies=[Depends(require_module_access("catalogo", "puedeVer"))])
def obtener_catalogo(empresa_id: int, db: Session = Depends(get_db), auth=Depends(get_current_auth_context)):
    assert_same_empresa(auth, empresa_id)

    cache_key = f"catalogo:{empresa_id}"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached

    productos = (
        db.query(Producto)
        .options(joinedload(Producto.categoria))
        .filter(
            Producto.activo == True,
            Producto.empresaID == empresa_id
        )
        .order_by(Producto.ordenCatalogo.asc())
        .all()
    )

    response = [
        {
            "idProducto": p.idProducto,
            "nombreProducto": p.nombreProducto,
            "precio": float(p.precioBase),
            "imagenUrl": p.imagenUrl,
            "esDestacado": p.esDestacado,
            "ordenCatalogo": p.ordenCatalogo,
            "nombreCategoria": p.categoria.nombreCategoria if p.categoria else None
        }
        for p in productos
    ]

    # Product catalog is read-heavy and changes less frequently.
    set_cache(cache_key, response, ttl=600)
    return response