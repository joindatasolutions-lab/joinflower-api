"""Customer profile and purchase history; communications are manual records."""
from datetime import date, datetime, time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.security import get_current_auth_context, require_module_access
from app.core.timezone import colombia_now_naive
from app.database import get_db
from app.models.cliente import Cliente
from app.models.pedido import Pedido
from app.models.estadopedido import EstadoPedido
from app.schemas.pedido import PedidoDetalleResponse
from app.routers import cliente as customers

router = APIRouter(prefix="/tenants/{tenant_id}/customers", tags=["Ficha de clientes"])
read_access = [Depends(require_module_access("pedidos", "puedeVer"))]
write_access = [Depends(require_module_access("pedidos", "puedeEditar"))]


class ProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    address: str | None = Field(default=None, max_length=500)
    preferred_channel: str | None = Field(default=None, max_length=100)
    preferred_occasion: str | None = Field(default=None, max_length=100)
    preferences: str | None = Field(default=None, max_length=10000)


class NoteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    content: str = Field(min_length=1, max_length=10000)


class CommunicationCreate(NoteCreate):
    channel: Literal["WHATSAPP", "EMAIL", "PHONE", "IN_PERSON", "OTHER"]
    direction: Literal["INBOUND", "OUTBOUND"]
    occurred_at: datetime | None = None

    @field_validator("occurred_at")
    @classmethod
    def local_time(cls, value):
        if value is not None and value.tzinfo is not None:
            from zoneinfo import ZoneInfo
            return value.astimezone(ZoneInfo("America/Bogota")).replace(tzinfo=None)
        return value


def _customer(db, auth, tenant_id, customer_id):
    empresa_id = customers._resolve_empresa_id(auth, tenant_id)
    customer = db.query(Cliente).filter(
        Cliente.empresaID == empresa_id, Cliente.idCliente == customer_id
    ).first()
    if customer is None:
        raise HTTPException(404, "Cliente no encontrado")
    return customer


def _profile(db, tenant_id, customer_id):
    row = db.execute(text("""
        SELECT direccion AS address, canal_preferido AS preferred_channel,
               ocasion_preferida AS preferred_occasion, preferencias AS preferences
        FROM petalops.cliente_perfil WHERE empresa_id=:tenant AND cliente_id=:customer
    """), {"tenant": tenant_id, "customer": customer_id}).mappings().first()
    return dict(row) if row else ProfilePatch().model_dump()


@router.get("/{customer_id}", dependencies=read_access)
def customer_detail(tenant_id: int, customer_id: int, db: Session = Depends(get_db),
                    auth=Depends(get_current_auth_context)):
    customer = _customer(db, auth, tenant_id, customer_id)
    today = colombia_now_naive().date()
    # Keep the tenant population for the existing HIGH_VALUE percentile.
    rows = customers._decorate_customer_segments(customers._customer_metric_rows(
        db, empresa_id=tenant_id, start_date=None, end_date=today, today=today
    ), start_date=None, end_date=today, today=today)
    row = next((r for r in rows if r["customer_id"] == customer_id), None)
    return {
        "customer": customers._cliente_to_dict(customer),
        "profile": _profile(db, tenant_id, customer_id),
        "metrics": customers._customer_metric_item(row) if row else None,
        "opportunities": customers._customer_special_date_opportunities(
            [row], today=today, max_days=365
        ) if row else [],
    }


@router.patch("/{customer_id}/profile", dependencies=write_access)
def update_profile(tenant_id: int, customer_id: int, payload: ProfilePatch,
                   db: Session = Depends(get_db), auth=Depends(get_current_auth_context)):
    _customer(db, auth, tenant_id, customer_id)
    values = payload.model_dump(exclude_unset=True)
    if values:
        columns = {"address": "direccion", "preferred_channel": "canal_preferido",
                   "preferred_occasion": "ocasion_preferida", "preferences": "preferencias"}
        names = [columns[key] for key in values]
        updates = ", ".join(f"{name}=EXCLUDED.{name}" for name in names)
        db.execute(text(f"""
            INSERT INTO petalops.cliente_perfil (empresa_id, cliente_id, {', '.join(names)})
            VALUES (:tenant, :customer, {', '.join(':'+key for key in values)})
            ON CONFLICT (cliente_id) DO UPDATE SET {updates},
                updated_at=timezone('America/Bogota', now())
            WHERE cliente_perfil.empresa_id=EXCLUDED.empresa_id
        """), {"tenant": tenant_id, "customer": customer_id, **values})
        db.commit()
    return {"profile": _profile(db, tenant_id, customer_id)}


@router.get("/{customer_id}/orders", dependencies=read_access)
def customer_orders(tenant_id: int, customer_id: int,
                    start_date: date | None = None, end_date: date | None = None,
                    status: str | None = None, page: int = Query(1, ge=1),
                    limit: int = Query(20, ge=1, le=100),
                    db: Session = Depends(get_db), auth=Depends(get_current_auth_context)):
    _customer(db, auth, tenant_id, customer_id)
    if start_date and end_date and start_date > end_date:
        raise HTTPException(400, "start_date no puede ser mayor que end_date")
    query = db.query(Pedido, EstadoPedido.nombreEstado).outerjoin(
        EstadoPedido, EstadoPedido.idEstadoPedido == Pedido.estadoPedidoID
    ).filter(Pedido.empresaID == tenant_id, Pedido.clienteID == customer_id)
    if start_date:
        query = query.filter(Pedido.fechaPedido >= datetime.combine(start_date, time.min))
    if end_date:
        query = query.filter(Pedido.fechaPedido <= datetime.combine(end_date, time.max))
    if status:
        query = query.filter(func.upper(func.trim(EstadoPedido.nombreEstado)) == status.strip().upper())
    total = query.count()
    rows = query.order_by(Pedido.fechaPedido.desc().nullslast(), Pedido.idPedido.desc()).offset(
        (page - 1) * limit).limit(limit).all()
    return {"total": total, "page": page, "limit": limit, "data": [
        {"order_id": p.idPedido, "number": p.numeroPedido, "code": p.codigoPedido,
         "ordered_at": p.fechaPedido, "status": state,
         "total": float(p.totalNeto if p.totalNeto is not None else p.totalBruto or 0),
         "delivery_cost": float(p.costoDomicilio or 0),
         "counts_as_purchase": (state or "").strip().upper() in customers.CUSTOMER_EFFECTIVE_PURCHASE_STATES}
        for p, state in rows]}


@router.get("/{customer_id}/orders/{order_id}", response_model=PedidoDetalleResponse, dependencies=read_access)
def customer_order_detail(tenant_id: int, customer_id: int, order_id: int,
                          db: Session = Depends(get_db), auth=Depends(get_current_auth_context)):
    _customer(db, auth, tenant_id, customer_id)
    order = db.query(Pedido.idPedido).filter(Pedido.empresaID == tenant_id,
        Pedido.clienteID == customer_id, Pedido.idPedido == order_id).first()
    if order is None:
        raise HTTPException(404, "Pedido no encontrado para este cliente")
    from app.routers.pedido import obtener_detalle_pedido
    return obtener_detalle_pedido(order_id, db=db, auth=auth)


def _interactions(db, tenant_id, customer_id, kind, page, limit):
    params = {"tenant": tenant_id, "customer": customer_id, "kind": kind,
              "limit": limit, "offset": (page - 1) * limit}
    where = "empresa_id=:tenant AND cliente_id=:customer AND tipo=:kind"
    total = db.execute(text(f"SELECT count(*) FROM petalops.cliente_interaccion WHERE {where}"), params).scalar_one()
    rows = db.execute(text(f"""
        SELECT id, contenido AS content, canal AS channel, direccion AS direction,
               ocurrido_at AS occurred_at, autor_id AS author_id, created_at
        FROM petalops.cliente_interaccion WHERE {where}
        ORDER BY ocurrido_at DESC, id DESC LIMIT :limit OFFSET :offset
    """), params).mappings().all()
    return {"total": total, "page": page, "limit": limit, "data": [dict(r) for r in rows]}


def _record(db, auth, tenant_id, customer_id, kind, payload):
    _customer(db, auth, tenant_id, customer_id)
    row = db.execute(text("""
        INSERT INTO petalops.cliente_interaccion
            (empresa_id, cliente_id, tipo, contenido, canal, direccion, ocurrido_at, autor_id)
        VALUES (:tenant, :customer, :kind, :content, :channel, :direction, :occurred, :author)
        RETURNING id, contenido AS content, canal AS channel, direccion AS direction,
                  ocurrido_at AS occurred_at, autor_id AS author_id, created_at
    """), {"tenant": tenant_id, "customer": customer_id, "kind": kind,
           "content": payload.content, "channel": getattr(payload, "channel", None),
           "direction": getattr(payload, "direction", None),
           "occurred": getattr(payload, "occurred_at", None) or colombia_now_naive(),
           "author": auth.userID}).mappings().one()
    result = dict(row)
    db.commit()
    return result


@router.get("/{customer_id}/notes", dependencies=read_access)
def customer_notes(tenant_id: int, customer_id: int, page: int = Query(1, ge=1),
                   limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db),
                   auth=Depends(get_current_auth_context)):
    _customer(db, auth, tenant_id, customer_id)
    return _interactions(db, tenant_id, customer_id, "NOTE", page, limit)


@router.post("/{customer_id}/notes", status_code=201, dependencies=write_access)
def create_note(tenant_id: int, customer_id: int, payload: NoteCreate,
                db: Session = Depends(get_db), auth=Depends(get_current_auth_context)):
    return _record(db, auth, tenant_id, customer_id, "NOTE", payload)


@router.get("/{customer_id}/communications", dependencies=read_access)
def customer_communications(tenant_id: int, customer_id: int, page: int = Query(1, ge=1),
                            limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db),
                            auth=Depends(get_current_auth_context)):
    _customer(db, auth, tenant_id, customer_id)
    return _interactions(db, tenant_id, customer_id, "COMMUNICATION", page, limit)


@router.post("/{customer_id}/communications", status_code=201, dependencies=write_access)
def create_communication(tenant_id: int, customer_id: int, payload: CommunicationCreate,
                         db: Session = Depends(get_db), auth=Depends(get_current_auth_context)):
    """Record an interaction manually. This operation does not send messages."""
    return _record(db, auth, tenant_id, customer_id, "COMMUNICATION", payload)
