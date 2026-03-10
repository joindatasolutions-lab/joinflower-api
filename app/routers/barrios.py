from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.barrio import Barrio
from app.core.security import assert_same_empresa, get_current_auth_context, require_module_access

router = APIRouter()


@router.get("/barrios/search", dependencies=[Depends(require_module_access("pedidos", "puedeVer"))])
def search_barrios(
    q: str = Query(...),
    empresa_id: int = Query(...),
    sucursal_id: int = Query(...),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)
    texto = q.strip()
    if len(texto) < 2:
        return []

    barrios = (
        db.query(Barrio)
        .filter(
            Barrio.activo == True,
            Barrio.empresaID == empresa_id,
            Barrio.sucursalID == sucursal_id,
            Barrio.nombreBarrio.ilike(f"%{texto}%"),
        )
        .order_by(Barrio.nombreBarrio.asc())
        .limit(10)
        .all()
    )

    return [
        {
            "idBarrio": barrio.idBarrio,
            "nombreBarrio": barrio.nombreBarrio,
            "costoDomicilio": float(barrio.costoDomicilio),
        }
        for barrio in barrios
    ]
