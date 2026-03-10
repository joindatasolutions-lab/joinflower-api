from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.empresa import Empresa

router = APIRouter()


class ActualizarSlugRequest(BaseModel):
    slug: str


def _normalizar_slug(value: str) -> str:
    value = (value or "").strip().lower()
    # Si llega dominio completo, usa solo subdominio como slug.
    return value.split(".")[0] if "." in value else value


@router.get("/empresa/por-dominio/{slug}")
def obtener_empresa_por_dominio(slug: str, db: Session = Depends(get_db)):
    # Compatibilidad hacia atras: resuelve por slug aunque el path diga dominio.
    return obtener_empresa_por_slug(slug=slug, db=db)


@router.get("/empresa/por-slug/{slug}")
def obtener_empresa_por_slug(slug: str, db: Session = Depends(get_db)):
    slug_normalizado = _normalizar_slug(slug)

    empresa = (
        db.query(Empresa)
        .filter(Empresa.slug == slug_normalizado)
        .first()
    )

    if not empresa:
        return JSONResponse(
            status_code=404,
            content={"error": "empresa no encontrada"},
        )

    return {
        "empresaId": empresa.idEmpresa,
        "nombre": empresa.nombreEmpresa,
        "nombreComercial": empresa.nombreComercial,
        "logoUrl": empresa.logoUrl,
    }


@router.put("/empresa/{empresa_id}/slug")
def actualizar_slug_empresa(
    empresa_id: int,
    payload: ActualizarSlugRequest,
    db: Session = Depends(get_db),
):
    nuevo_slug = _normalizar_slug(payload.slug)
    if not nuevo_slug:
        return JSONResponse(status_code=400, content={"error": "slug invalido"})

    empresa = db.query(Empresa).filter(Empresa.idEmpresa == empresa_id).first()
    if not empresa:
        return JSONResponse(status_code=404, content={"error": "empresa no encontrada"})

    slug_en_uso = (
        db.query(Empresa)
        .filter(Empresa.slug == nuevo_slug, Empresa.idEmpresa != empresa_id)
        .first()
    )
    if slug_en_uso:
        return JSONResponse(status_code=409, content={"error": "slug ya existe"})

    empresa.slug = nuevo_slug
    db.commit()

    return {
        "empresaId": empresa.idEmpresa,
        "slug": empresa.slug,
    }
