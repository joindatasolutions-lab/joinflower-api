from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.cliente import Cliente

router = APIRouter()


@router.get("/cliente/buscar/{empresaID}/{identificacion}")
def buscar_cliente(
    empresa_id: int = Path(alias="empresaID"),
    identificacion: str = Path(...),
    db: Session = Depends(get_db),
):
    cliente = (
        db.query(Cliente)
        .filter(
            Cliente.empresaID == empresa_id,
            Cliente.identificacion == identificacion,
        )
        .first()
    )

    if not cliente:
        return {"existe": False}

    return {
        "existe": True,
        "cliente": {
            "tipoIdent": cliente.tipoIdent,
            "nombreCompleto": cliente.nombreCompleto,
            "indicativo": cliente.indicativo,
            "telefono": cliente.telefono,
            "telefonoCompleto": cliente.telefonoCompleto,
            "email": cliente.email,
        },
    }
