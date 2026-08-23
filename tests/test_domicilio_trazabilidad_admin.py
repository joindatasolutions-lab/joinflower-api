from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.entrega import Entrega
from app.models.pedido import Pedido
from app.models.produccion import Produccion
from app.routers import domicilios as domicilios_router
from app.schemas.domicilios import DomicilioTrazabilidadCorreccionRequest


class FakeQuery:
    def __init__(self, first_value=None, all_value=None):
        self._first_value = first_value
        self._all_value = all_value or []

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def with_for_update(self, *args, **kwargs):
        return self

    def first(self):
        return self._first_value

    def all(self):
        return self._all_value


class FakeDb:
    def __init__(self, pedido=None, entrega=None, producciones=None):
        self.pedido = pedido
        self.entrega = entrega
        self.producciones = producciones or []
        self.committed = False

    def query(self, *entities):
        if entities == (Pedido,):
            return FakeQuery(first_value=self.pedido)
        if entities == (Entrega,):
            return FakeQuery(first_value=self.entrega)
        if entities == (Produccion,):
            return FakeQuery(all_value=self.producciones)
        raise AssertionError(f"Unexpected query entities: {entities}")

    def commit(self):
        self.committed = True


def _pedido():
    return SimpleNamespace(idPedido=20, empresaID=3, sucursalID=1, fechaPedido=datetime(2026, 8, 8, 9, 0, 0))


def _entrega(**overrides):
    data = {
        "idEntrega": 10,
        "empresaID": 3,
        "sucursalID": 1,
        "pedidoID": 20,
        "estadoEntregaID": 4,
        "domiciliarioID": 48,
        "intentoNumero": 1,
        "fechaAsignacion": datetime(2026, 8, 8, 17, 20, 0),
        "fechaSalida": datetime(2026, 8, 8, 17, 40, 0),
        "fechaEntrega": datetime(2026, 8, 8, 19, 0, 0),
        "fechaEntregaProgramada": datetime(2026, 8, 8, 10, 0, 0),
        "reprogramadaPara": None,
        "updatedAt": None,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _payload(estado="Entregado", fecha=None, motivo="Correccion administrativa con soporte operativo"):
    return DomicilioTrazabilidadCorreccionRequest(
        estado=estado,
        fecha_efectiva=fecha or datetime(2026, 8, 8, 18, 35, 0),
        motivo=motivo,
    )


def _admin_auth():
    return SimpleNamespace(empresaID=3, esGlobalJoin=False, rol="admin", userID=100, login="flora.admin")


def test_corregir_trazabilidad_requires_admin():
    db = FakeDb()
    auth = SimpleNamespace(empresaID=3, esGlobalJoin=False, rol="domiciliario", userID=101, login="domi")

    with pytest.raises(HTTPException) as exc:
        domicilios_router.corregir_trazabilidad_pedido(20, _payload(), db=db, auth=auth)

    assert exc.value.status_code == 403


def test_corregir_trazabilidad_rejects_fecha_fuera_de_entrega_programada(monkeypatch):
    monkeypatch.setattr(domicilios_router, "_audit_domicilio_action", lambda **kwargs: None)
    db = FakeDb(pedido=_pedido(), entrega=_entrega())

    with pytest.raises(HTTPException) as exc:
        domicilios_router.corregir_trazabilidad_pedido(
            20,
            _payload(fecha=datetime(2026, 8, 9, 18, 35, 0)),
            db=db,
            auth=_admin_auth(),
        )

    assert exc.value.status_code == 400
    assert db.committed is False


def test_corregir_trazabilidad_rejects_secuencia_invalida(monkeypatch):
    monkeypatch.setattr(domicilios_router, "_audit_domicilio_action", lambda **kwargs: None)
    db = FakeDb(pedido=_pedido(), entrega=_entrega(fechaSalida=datetime(2026, 8, 8, 18, 0, 0)))

    with pytest.raises(HTTPException) as exc:
        domicilios_router.corregir_trazabilidad_pedido(
            20,
            _payload(estado="Asignado", fecha=datetime(2026, 8, 8, 18, 30, 0)),
            db=db,
            auth=_admin_auth(),
        )

    assert exc.value.status_code == 400
    assert db.committed is False


def test_corregir_trazabilidad_updates_fecha_entrega_and_audits(monkeypatch):
    audit_calls = []
    monkeypatch.setattr(domicilios_router, "_audit_domicilio_action", lambda **kwargs: audit_calls.append(kwargs))
    entrega = _entrega()
    db = FakeDb(pedido=_pedido(), entrega=entrega)

    response = domicilios_router.corregir_trazabilidad_pedido(
        20,
        _payload(),
        db=db,
        auth=_admin_auth(),
    )

    assert response.status == "ok"
    assert response.pedidoID == 20
    assert response.estado == domicilios_router.ESTADO_ENTREGADO
    assert response.fechaAnterior == datetime(2026, 8, 8, 19, 0, 0)
    assert entrega.fechaEntrega == datetime(2026, 8, 8, 18, 35, 0)
    assert entrega.updatedAt == response.fechaModificacion
    assert db.committed is True
    assert audit_calls[0]["accion"] == "CORRECCION_TRAZABILIDAD"
    assert audit_calls[0]["extra"]["fechaAnterior"] == "2026-08-08T19:00:00"
    assert audit_calls[0]["extra"]["fechaNueva"] == "2026-08-08T18:35:00"
    assert audit_calls[0]["extra"]["usuarioAdmin"] == "flora.admin"
