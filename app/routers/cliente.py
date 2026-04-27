from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.security import assert_same_empresa, get_current_auth_context, require_module_access
from app.database import get_db
from app.models.cliente import Cliente
from app.schemas.cliente import ClientePayload, ClienteUpdatePayload

router = APIRouter()


def _resolve_empresa_id(auth, empresa_id: int | None) -> int:
    if empresa_id is None:
        if auth.empresaID in (None, 0):
            raise HTTPException(status_code=400, detail="empresaID es obligatorio para este usuario")
        return int(auth.empresaID)
    assert_same_empresa(auth, int(empresa_id))
    return int(empresa_id)


def _cliente_to_dict(cliente: Cliente) -> dict:
    return {
        "clienteID": int(cliente.idCliente),
        "empresaID": int(cliente.empresaID or 0),
        "tipoIdent": str(cliente.tipoIdent or "").strip() or None,
        "identificacion": str(cliente.identificacion or "").strip() or None,
        "indicativo": str(cliente.indicativo or "").strip() or None,
        "nombreCompleto": str(cliente.nombreCompleto or "").strip(),
        "telefono": str(cliente.telefono or "").strip() or None,
        "telefonoCompleto": str(cliente.telefonoCompleto or "").strip() or None,
        "email": str(cliente.email or "").strip() or None,
        "fechaCumpleanos": cliente.fechaCumpleanos.isoformat() if cliente.fechaCumpleanos else None,
        "fechaAniversario": cliente.fechaAniversario.isoformat() if cliente.fechaAniversario else None,
        "activo": bool(cliente.activo),
        "createdAt": cliente.createdAt.isoformat() if cliente.createdAt else None,
        "updatedAt": cliente.updatedAt.isoformat() if cliente.updatedAt else None,
    }


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
            "fechaCumpleanos": cliente.fechaCumpleanos.isoformat() if cliente.fechaCumpleanos else None,
            "fechaAniversario": cliente.fechaAniversario.isoformat() if cliente.fechaAniversario else None,
        },
    }


@router.get("/clientes", dependencies=[Depends(require_module_access("pedidos", "puedeVer"))])
def list_clientes(
    empresa_id: int | None = Query(default=None, alias="empresaID"),
    q: str = Query(default=""),
    solo_activos: bool = Query(default=False, alias="soloActivos"),
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    scoped_empresa_id = _resolve_empresa_id(auth, empresa_id)
    texto = str(q or "").strip()

    query = db.query(Cliente).filter(Cliente.empresaID == scoped_empresa_id)

    if solo_activos:
        query = query.filter(Cliente.activo.is_(True))

    if texto:
        like = f"%{texto}%"
        query = query.filter(
            or_(
                Cliente.nombreCompleto.ilike(like),
                Cliente.identificacion.ilike(like),
                Cliente.telefono.ilike(like),
                Cliente.telefonoCompleto.ilike(like),
                Cliente.email.ilike(like),
            )
        )

    clientes = (
        query
        .order_by(Cliente.updatedAt.desc().nullslast(), Cliente.idCliente.desc())
        .all()
    )

    return {
        "items": [_cliente_to_dict(cliente) for cliente in clientes],
        "total": len(clientes),
    }


@router.post("/clientes", dependencies=[Depends(require_module_access("pedidos", "puedeCrear"))])
def create_cliente(
    payload: ClientePayload,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    scoped_empresa_id = _resolve_empresa_id(auth, int(payload.empresaID))

    identificacion = str(payload.identificacion or "").strip()
    telefono_completo = str(payload.telefonoCompleto or "").strip() or None
    email = str(payload.email or "").strip().lower() or None

    existing = None
    if identificacion:
        existing = (
            db.query(Cliente)
            .filter(
                Cliente.empresaID == scoped_empresa_id,
                Cliente.identificacion == identificacion,
            )
            .first()
        )
    if existing:
        raise HTTPException(status_code=400, detail="Ya existe un cliente con esa identificación")

    now = datetime.now(timezone.utc)
    cliente = Cliente(
        empresaID=scoped_empresa_id,
        tipoIdent=str(payload.tipoIdent or "").strip() or None,
        identificacion=identificacion or None,
        indicativo=str(payload.indicativo or "").strip() or None,
        nombreCompleto=str(payload.nombreCompleto or "").strip(),
        telefono=str(payload.telefono or "").strip() or None,
        telefonoCompleto=telefono_completo,
        email=email,
        fechaCumpleanos=payload.fechaCumpleanos,
        fechaAniversario=payload.fechaAniversario,
        activo=1 if bool(payload.activo) else 0,
        createdAt=now,
        updatedAt=now,
    )
    db.add(cliente)
    db.commit()
    db.refresh(cliente)

    return {"status": "ok", "cliente": _cliente_to_dict(cliente)}


@router.put("/clientes/{cliente_id}", dependencies=[Depends(require_module_access("pedidos", "puedeEditar"))])
def update_cliente(
    cliente_id: int,
    payload: ClienteUpdatePayload,
    db: Session = Depends(get_db),
    auth=Depends(get_current_auth_context),
):
    scoped_empresa_id = _resolve_empresa_id(auth, int(payload.empresaID))

    cliente = (
        db.query(Cliente)
        .filter(
            Cliente.idCliente == int(cliente_id),
            Cliente.empresaID == scoped_empresa_id,
        )
        .first()
    )
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    identificacion = str(payload.identificacion or "").strip() or None
    if identificacion:
        existing = (
            db.query(Cliente)
            .filter(
                Cliente.empresaID == scoped_empresa_id,
                Cliente.identificacion == identificacion,
                Cliente.idCliente != int(cliente_id),
            )
            .first()
        )
        if existing:
            raise HTTPException(status_code=400, detail="Ya existe otro cliente con esa identificación")

    cliente.tipoIdent = str(payload.tipoIdent or "").strip() or None
    cliente.identificacion = identificacion
    cliente.indicativo = str(payload.indicativo or "").strip() or None
    cliente.nombreCompleto = str(payload.nombreCompleto or "").strip()
    cliente.telefono = str(payload.telefono or "").strip() or None
    cliente.telefonoCompleto = str(payload.telefonoCompleto or "").strip() or None
    cliente.email = str(payload.email or "").strip().lower() or None
    cliente.fechaCumpleanos = payload.fechaCumpleanos
    cliente.fechaAniversario = payload.fechaAniversario
    cliente.activo = 1 if bool(payload.activo) else 0
    cliente.updatedAt = datetime.now(timezone.utc)
    db.commit()
    db.refresh(cliente)

    return {"status": "ok", "cliente": _cliente_to_dict(cliente)}
