from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.empresa_configuracion_asignacion import EmpresaConfiguracionAsignacion
from app.routers import produccion as produccion_router
from app.schemas.produccion import ProduccionReasignarRequest


class _FakeConfigQuery:
    def __init__(self, config):
        self._config = config

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._config


class _FakeDb:
    def __init__(self, config):
        self._config = config

    def query(self, model):
        assert model is EmpresaConfiguracionAsignacion
        return _FakeConfigQuery(self._config)


def test_reasignar_produccion_no_longer_blocks_non_admin_florista(monkeypatch):
    payload = ProduccionReasignarRequest(
        floristaNuevoID=7,
        fechaProgramadaProduccion=date(2026, 5, 10),
        motivo="Cambio manual",
        usuarioCambio="florista1",
    )
    auth = SimpleNamespace(
        login="florista1",
        nombre="Elibeth Salgado",
        empresaID=3,
        sucursalID=3,
        rol="Florista",
        userID=12,
        esGlobalJoin=False,
        roles=[],
    )
    # Esta floristeria activo el flag de autoasignacion (Acciones > Produccion);
    # sin eso, reasignar_produccion rechazaria a un florista no-admin con 403.
    config = EmpresaConfiguracionAsignacion(empresaID=3, asignacionProduccionActiva=True)
    db = _FakeDb(config)
    captured = {}

    def fake_asignar(produccion_id, wrapper, db_arg, auth_arg):
        captured["produccion_id"] = produccion_id
        captured["wrapper"] = wrapper
        captured["db"] = db_arg
        captured["auth"] = auth_arg
        return {"status": "ok"}

    monkeypatch.setattr(produccion_router, "asignar_produccion", fake_asignar)

    response = produccion_router.reasignar_produccion(92, payload, db, auth)

    assert response == {"status": "ok"}
    assert captured["produccion_id"] == 92
    assert captured["db"] is db
    assert captured["auth"] is auth
    assert captured["wrapper"].floristaID == 7
    assert captured["wrapper"].fechaProgramadaProduccion == date(2026, 5, 10)
    assert captured["wrapper"].motivo == "Cambio manual"
    assert captured["wrapper"].usuarioCambio == "florista1"


def test_reasignar_produccion_bloquea_florista_si_flag_apagado(monkeypatch):
    payload = ProduccionReasignarRequest(
        floristaNuevoID=7,
        fechaProgramadaProduccion=date(2026, 5, 10),
        motivo="Cambio manual",
        usuarioCambio="florista1",
    )
    auth = SimpleNamespace(
        login="florista1", nombre="Elibeth Salgado", empresaID=3, sucursalID=3,
        rol="Florista", userID=12, esGlobalJoin=False, roles=[],
    )
    db = _FakeDb(config=None)  # sin fila de configuracion => autoasignacion deshabilitada por defecto

    def fake_asignar(*args, **kwargs):
        raise AssertionError("no deberia llegar a asignar_produccion si el flag esta apagado")

    monkeypatch.setattr(produccion_router, "asignar_produccion", fake_asignar)

    with pytest.raises(HTTPException) as exc_info:
        produccion_router.reasignar_produccion(92, payload, db, auth)

    assert exc_info.value.status_code == 403


def test_reasignar_produccion_admin_no_depende_del_flag(monkeypatch):
    payload = ProduccionReasignarRequest(
        floristaNuevoID=7,
        fechaProgramadaProduccion=date(2026, 5, 10),
        motivo="Cambio manual",
        usuarioCambio="admin1",
    )
    auth = SimpleNamespace(
        login="admin1", nombre="Admin Tienda", empresaID=3, sucursalID=3,
        rol="Admin", userID=1, esGlobalJoin=False, roles=[],
    )
    db = _FakeDb(config=None)  # flag apagado/inexistente, pero el admin no depende de el
    captured = {}

    def fake_asignar(produccion_id, wrapper, db_arg, auth_arg):
        captured["called"] = True
        return {"status": "ok"}

    monkeypatch.setattr(produccion_router, "asignar_produccion", fake_asignar)

    response = produccion_router.reasignar_produccion(92, payload, db, auth)

    assert response == {"status": "ok"}
    assert captured.get("called") is True
