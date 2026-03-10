from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.cliente import Cliente
from app.core.security import assert_same_empresa, get_current_auth_context, require_module_access

router = APIRouter()


@router.get("/cliente/buscar/{empresaID}/{identificacion}", dependencies=[Depends(require_module_access("pedidos", "puedeVer"))])
def buscar_cliente(
    empresa_id: int = Path(alias="empresaID"),
    identificacion: str = Path(...),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    assert_same_empresa(auth, empresa_id)
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
