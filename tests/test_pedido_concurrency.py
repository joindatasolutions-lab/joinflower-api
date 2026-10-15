from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy import create_engine, text
from starlette.requests import Request

from app.services.pedido_concurrency import begin_creation, complete_creation, check_and_increment_version
from app.routers.pedido import ActualizarDetallePedidoRequest, AgregarDetallePedidoRequest


class Payload(BaseModel):
    nombre: str = "pedido"


def request(key="operation-1"):
    return Request({"type": "http", "headers": [(b"idempotency-key", key.encode())]})


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    with engine.connect() as conn:
        conn.execute(text("ATTACH DATABASE ':memory:' AS petalops"))
        conn.execute(text("CREATE TABLE petalops.pedido_operacion (empresa_id INTEGER, operacion TEXT, clave TEXT, payload_hash TEXT, respuesta_json TEXT, PRIMARY KEY (empresa_id, operacion, clave))"))
        conn.commit()
        class Adapter:
            # SQLite exercises transaction/replay semantics; row locks require PostgreSQL.
            def execute(self, statement, params):
                return conn.execute(text(str(statement).replace("FOR UPDATE", "")), params)
            def commit(self):
                conn.commit()
            def rollback(self):
                conn.rollback()
        yield Adapter()
    engine.dispose()


def begin(db, *, key="operation-1", empresa=1, operation="manual", payload=None):
    return begin_creation(db, request(key), empresa_id=empresa, operation=operation, payload=payload or Payload())


def test_creation_replays_exact_response_and_rejects_changed_payload(db):
    token, replay = begin(db)
    assert replay is None
    response = {"pedidoID": 123, "pedidoIDs": [123], "total": 150.5}
    complete_creation(db, token, response)
    db.commit()
    assert begin(db)[1] == response
    with pytest.raises(HTTPException) as error:
        begin(db, payload=Payload(nombre="different"))
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_failed_creation_can_retry_and_scopes_do_not_collide(db):
    begin(db)
    db.rollback()
    token, replay = begin(db)
    assert replay is None
    complete_creation(db, token, {"pedidoID": 1})
    db.commit()
    assert begin(db, empresa=2)[1] is None
    assert begin(db, operation="checkout")[1] is None


def test_resume_duplicate_after_creation_and_first_edit_committed(db):
    creation, _ = begin(db)
    complete_creation(db, creation, {"pedidoID": 10})
    db.commit()
    step, _ = begin(db, key="copy-step-1", operation="actualizar_detalle_pedido:10")
    complete_creation(db, step, {"pedidoID": 10, "version": 2})
    db.commit()
    begin(db, key="copy-step-2", operation="actualizar_detalle_pedido:10")
    db.rollback()  # Failure halfway through a later step.
    assert begin(db)[1] == {"pedidoID": 10}
    assert begin(db, key="copy-step-1", operation="actualizar_detalle_pedido:10")[1]["version"] == 2
    assert begin(db, key="copy-step-2", operation="actualizar_detalle_pedido:10")[1] is None


def test_incomplete_legacy_reservation_is_not_blindly_recreated(db):
    begin(db)
    db.commit()
    with pytest.raises(HTTPException) as error:
        begin(db)
    assert error.value.detail["code"] == "OPERATION_INCOMPLETE"


@pytest.mark.parametrize("key", ["", "x" * 129])
def test_creation_requires_bounded_key(db, key):
    with pytest.raises(HTTPException) as error:
        begin(db, key=key)
    assert error.value.status_code == 422


def test_stale_edit_cannot_overwrite_new_version():
    pedido = SimpleNamespace(version=1)
    check_and_increment_version(pedido, 1)
    assert pedido.version == 2
    with pytest.raises(HTTPException) as error:
        check_and_increment_version(pedido, 1)
    assert error.value.status_code == 409
    assert pedido.version == 2


@pytest.mark.parametrize("model", [ActualizarDetallePedidoRequest, AgregarDetallePedidoRequest])
def test_edit_contract_requires_positive_version(model):
    for value in ({}, {"version": 0}):
        with pytest.raises(ValidationError):
            model(productoID=1, **value)


@pytest.mark.parametrize("fail_audit", [False, True])
def test_checkout_persists_result_with_audit_or_rolls_back(db, monkeypatch, fail_audit):
    from app.routers import pedido as router
    from app.schemas.pedido import PedidoCheckoutRequest
    payload = PedidoCheckoutRequest(
        empresaID=1, sucursalID=1, productos=[{"productoID": 1, "cantidad": 1}],
        cliente={"nombreCompleto": "Cliente", "telefono": "123"},
        entrega={"direccion": "Calle", "fechaEntrega": "2026-09-27T12:00:00"},
    )
    calls = []
    pedido = SimpleNamespace(idPedido=10, empresaID=1, estadoPedidoID=1, numeroPedido=1, codigoPedido="P1", totalNeto=100)
    class Query:
        def filter(self, *args):
            return self
        def first(self):
            return pedido
    db.query = lambda *args: Query()
    monkeypatch.setattr(router, "assert_same_empresa", lambda *args: None)
    monkeypatch.setattr(router, "assert_sucursal_empresa", lambda *args: None)
    def create(*, db, payload, commit):
        assert commit is False
        calls.append("create")
        return {"pedidoID": 10, "total": 100, "estado": "CREADO"}
    monkeypatch.setattr(router, "checkout_pedido", create)
    def audit(**kwargs):
        if fail_audit:
            raise RuntimeError("audit unavailable")
    monkeypatch.setattr(router, "_audit_pedido_action", audit)
    def run():
        return router.checkout.__wrapped__(request=request(), data=payload, db=db, auth=SimpleNamespace(empresaID=1))
    if fail_audit:
        with pytest.raises(RuntimeError):
            run()
        # Reservation was rolled back: retry reaches creation again.
        with pytest.raises(RuntimeError):
            run()
        assert calls == ["create", "create"]
    else:
        first = run()
        assert run() == first
        assert calls == ["create"]
