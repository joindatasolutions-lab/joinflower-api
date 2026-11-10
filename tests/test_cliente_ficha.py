from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.models.cliente import Cliente
from app.models.pedido import Pedido
from app.models.estadopedido import EstadoPedido
from app.routers import cliente_ficha as ficha
from app.routers.cliente import list_clientes


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    with engine.connect() as conn:
        conn.connection.driver_connection.create_function("now", 0, lambda: "2026-10-19 12:00:00")
        conn.connection.driver_connection.create_function("timezone", 2, lambda zone, value: value)
        conn.execute(text("ATTACH DATABASE ':memory:' AS petalops"))
        Cliente.__table__.create(conn)
        EstadoPedido.__table__.create(conn)
        Pedido.__table__.create(conn)
        conn.execute(text("""CREATE TABLE petalops.cliente_perfil (
            cliente_id INTEGER PRIMARY KEY, empresa_id INTEGER, direccion TEXT,
            canal_preferido TEXT, ocasion_preferida TEXT, preferencias TEXT, updated_at TIMESTAMP)"""))
        conn.execute(text("""CREATE TABLE petalops.cliente_interaccion (
            id INTEGER PRIMARY KEY, empresa_id INTEGER, cliente_id INTEGER,
            tipo TEXT, contenido TEXT, canal TEXT, direccion TEXT,
            ocurrido_at TIMESTAMP, autor_id INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""))
        conn.commit()
        with Session(conn) as session:
            session.add_all([
                Cliente(idCliente=1, empresaID=3, nombreCompleto="Ana", activo=1),
                Cliente(idCliente=2, empresaID=4, nombreCompleto="Otro tenant", activo=1),
                Cliente(idCliente=3, empresaID=3, nombreCompleto="Sin compras", activo=1),
                EstadoPedido(idEstadoPedido=1, nombreEstado="APROBADO"),
                EstadoPedido(idEstadoPedido=2, nombreEstado="RECHAZADO"),
            ])
            for order_id, tenant, customer, state in [(10, 3, 1, 1), (11, 3, 1, 2), (12, 4, 2, 1)]:
                session.add(Pedido(idPedido=order_id, empresaID=tenant, clienteID=customer,
                    sucursalID=1, numeroPedido=order_id, estadoPedidoID=state,
                    fechaPedido=datetime(2026, 10, 19, 12), totalNeto=0, totalBruto=100))
            session.commit()
            yield session
    engine.dispose()


@pytest.fixture
def auth():
    return SimpleNamespace(empresaID=3, userID=7, rol="USER", esGlobalJoin=False)


def test_history_is_scoped_paginated_and_preserves_zero_total(db, auth):
    result = ficha.customer_orders(3, 1, page=1, limit=1, db=db, auth=auth)
    assert result["total"] == 2
    assert result["data"][0]["order_id"] == 11
    assert result["data"][0]["total"] == 0
    assert result["data"][0]["counts_as_purchase"] is False
    approved = ficha.customer_orders(3, 1, status="aprobado", page=1, limit=20, db=db, auth=auth)
    assert [r["order_id"] for r in approved["data"]] == [10]
    assert ficha.customer_orders(3, 3, page=1, limit=20, db=db, auth=auth)["data"] == []


def test_cross_tenant_and_wrong_customer_order_are_rejected(db, auth):
    with pytest.raises(HTTPException) as exc:
        ficha.customer_detail(4, 2, db=db, auth=auth)
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        ficha.customer_order_detail(3, 1, 12, db=db, auth=auth)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        ficha.customer_order_detail(3, 3, 10, db=db, auth=auth)
    assert exc.value.status_code == 404


def test_notes_and_communications_are_separate_and_author_is_authenticated(db, auth):
    note = ficha.create_note(3, 1, ficha.NoteCreate(content=" Prefiere rosas "), db=db, auth=auth)
    assert note["content"] == "Prefiere rosas"
    assert note["author_id"] == 7
    ficha.create_communication(3, 1, ficha.CommunicationCreate(
        content="Llamada recibida", channel="PHONE", direction="INBOUND"), db=db, auth=auth)
    assert ficha.customer_notes(3, 1, page=1, limit=20, db=db, auth=auth)["total"] == 1
    assert ficha.customer_communications(3, 1, page=1, limit=20, db=db, auth=auth)["total"] == 1
    assert ficha.customer_notes(3, 3, page=1, limit=20, db=db, auth=auth)["total"] == 0
    with pytest.raises(HTTPException):
        ficha.create_note(3, 2, ficha.NoteCreate(content="No permitido"), db=db, auth=auth)


def test_input_validation_and_timezone():
    with pytest.raises(ValidationError):
        ficha.NoteCreate(content="   ")
    with pytest.raises(ValidationError):
        ficha.NoteCreate(content="Nota", author_id=99)
    payload = ficha.CommunicationCreate(content="Contacto", channel="EMAIL", direction="OUTBOUND",
                                        occurred_at="2026-10-19T15:00:00Z")
    assert payload.occurred_at == datetime(2026, 10, 19, 10)
    assert ficha.ProfilePatch(address=None).model_dump(exclude_unset=True) == {"address": None}


def test_sidebar_filters_before_pagination(db, auth):
    args = dict(empresa_id=3, q="", solo_activos=True, include_metrics=False,
                start_date=None, end_date=None, page=1, page_size=1, db=db, auth=auth)
    buyers = list_clientes(**args, has_purchases=True)
    non_buyers = list_clientes(**args, has_purchases=False)
    assert buyers["total"] == 1
    assert buyers["items"][0]["clienteID"] == 1
    assert non_buyers["total"] == 1
    assert non_buyers["items"][0]["clienteID"] == 3


def test_profile_detail_handles_non_buyer(db, auth, monkeypatch):
    monkeypatch.setattr(ficha.customers, "_customer_metric_rows", lambda *a, **kw: [
        {"customer_id": 3, "name": "Sin compras", "purchase_count": 0, "total_spent": 0}
    ])
    result = ficha.customer_detail(3, 3, db=db, auth=auth)
    assert result["customer"]["activo"] is True
    assert result["metrics"]["purchase_count"] == 0
    assert result["metrics"]["first_purchase_at"] is None
    assert result["profile"]["address"] is None
    assert result["opportunities"] == []


def test_profile_patch_preserves_omitted_fields_and_allows_clearing(db, auth):
    ficha.update_profile(3, 1, ficha.ProfilePatch(address="Calle 10", preferred_occasion="Cumpleaños"), db=db, auth=auth)
    result = ficha.update_profile(3, 1, ficha.ProfilePatch(preferred_channel="WhatsApp"), db=db, auth=auth)
    assert result["profile"]["address"] == "Calle 10"
    assert result["profile"]["preferred_channel"] == "WhatsApp"
    result = ficha.update_profile(3, 1, ficha.ProfilePatch(address=None), db=db, auth=auth)
    assert result["profile"]["address"] is None
    assert result["profile"]["preferred_occasion"] == "Cumpleaños"
    with pytest.raises(HTTPException):
        ficha.update_profile(3, 2, ficha.ProfilePatch(address="No permitido"), db=db, auth=auth)
