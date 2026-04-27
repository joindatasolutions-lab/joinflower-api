from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import String, cast, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.barrio import Barrio
from app.core.security import assert_same_empresa, get_current_auth_context, require_module_access
from app.services.cache import get_cache, set_cache

router = APIRouter()


def _activo_truthy(column):
    return func.lower(cast(column, String)).in_(["true", "t", "1"])


class BarrioCreateRequest(BaseModel):
    sucursalID: int = Field(alias="sucursalID")
    zonaID: int = Field(alias="zonaID", ge=0)
    nombreBarrio: str = Field(min_length=2, max_length=150)
    costoDomicilio: float = Field(ge=0)
    activo: bool = True


class BarrioUpdateRequest(BaseModel):
    sucursalID: int = Field(alias="sucursalID")
    nombreBarrio: str = Field(min_length=2, max_length=150)
    costoDomicilio: float = Field(ge=0)


@router.get("/barrios", dependencies=[Depends(require_module_access("domicilios", "puedeVer"))])
def list_barrios(
    sucursal_id: int = Query(..., alias="sucursalID"),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    empresa_id = int(auth.empresaID)

    barrios = (
        db.query(Barrio)
        .filter(
            Barrio.empresaID == empresa_id,
            Barrio.sucursalID == sucursal_id,
        )
        .order_by(Barrio.nombreBarrio.asc())
        .all()
    )

    return {
        "items": [
            {
                "idBarrio": int(barrio.idBarrio),
                "zonaID": int(barrio.zonaID or 0),
                "nombreBarrio": str(barrio.nombreBarrio or ""),
                "costoDomicilio": float(barrio.costoDomicilio or 0),
                "activo": bool(barrio.activo),
            }
            for barrio in barrios
        ],
        "total": len(barrios),
    }


@router.post("/barrios", dependencies=[Depends(require_module_access("domicilios", "puedeCrear"))])
def create_barrio(
    payload: BarrioCreateRequest,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    empresa_id = int(auth.empresaID)

    existing = (
        db.query(Barrio)
        .filter(
            Barrio.empresaID == empresa_id,
            Barrio.sucursalID == int(payload.sucursalID),
            func.lower(Barrio.nombreBarrio) == payload.nombreBarrio.strip().lower(),
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Ya existe un barrio con ese nombre en la sucursal")

    barrio = Barrio(
        empresaID=empresa_id,
        sucursalID=int(payload.sucursalID),
        zonaID=int(payload.zonaID),
        nombreBarrio=payload.nombreBarrio.strip(),
        costoDomicilio=payload.costoDomicilio,
        activo=bool(payload.activo),
        createdAt=datetime.now(timezone.utc),
        updatedAt=datetime.now(timezone.utc),
    )
    db.add(barrio)
    db.commit()
    db.refresh(barrio)

    return {
        "status": "ok",
        "idBarrio": int(barrio.idBarrio),
        "zonaID": int(barrio.zonaID or 0),
        "nombreBarrio": str(barrio.nombreBarrio or ""),
        "costoDomicilio": float(barrio.costoDomicilio or 0),
        "activo": bool(barrio.activo),
    }


@router.put("/barrios/{barrio_id}", dependencies=[Depends(require_module_access("domicilios", "puedeEditar"))])
def update_barrio(
    barrio_id: int,
    payload: BarrioUpdateRequest,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    empresa_id = int(auth.empresaID)

    barrio = (
        db.query(Barrio)
        .filter(
            Barrio.idBarrio == barrio_id,
            Barrio.empresaID == empresa_id,
            Barrio.sucursalID == int(payload.sucursalID),
        )
        .first()
    )
    if not barrio:
        raise HTTPException(status_code=404, detail="Barrio no encontrado")

    existing = (
        db.query(Barrio)
        .filter(
            Barrio.empresaID == empresa_id,
            Barrio.sucursalID == int(payload.sucursalID),
            func.lower(Barrio.nombreBarrio) == payload.nombreBarrio.strip().lower(),
            Barrio.idBarrio != barrio_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Ya existe un barrio con ese nombre en la sucursal")

    barrio.nombreBarrio = payload.nombreBarrio.strip()
    barrio.costoDomicilio = payload.costoDomicilio
    barrio.updatedAt = datetime.now(timezone.utc)
    db.commit()
    db.refresh(barrio)

    return {
        "status": "ok",
        "idBarrio": int(barrio.idBarrio),
        "zonaID": int(barrio.zonaID or 0),
        "nombreBarrio": str(barrio.nombreBarrio or ""),
        "costoDomicilio": float(barrio.costoDomicilio or 0),
        "activo": bool(barrio.activo),
    }


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
