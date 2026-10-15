from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.sucursal import Sucursal


def assert_sucursal_empresa(db: Session, empresa_id: int, sucursal_id: int | None) -> None:
    """Validate branch ownership, including explicit targets of global admins."""
    if sucursal_id is None:
        return
    sucursal = db.query(Sucursal.idSucursal).filter(
        Sucursal.idSucursal == int(sucursal_id),
        Sucursal.empresaID == int(empresa_id),
    ).first()
    if sucursal is None:
        raise HTTPException(status_code=403, detail="Sucursal no pertenece a la empresa indicada")
