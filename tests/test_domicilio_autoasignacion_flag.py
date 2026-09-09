"""Verifica que /entregas/{id}/tomar respete el flag "Acciones > Domicilios"
(petalops.empresa_configuracion_asignacion.asignacion_domicilio_activa): un domiciliario
no-admin no puede autoasignarse una entrega si la floristeria no activo esa opcion.
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.empresa_configuracion_asignacion import EmpresaConfiguracionAsignacion
from app.routers import domicilios as domicilios_router
from app.schemas.domicilios import TomarEntregaRequest


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


FAKE_ENTREGA = SimpleNamespace(idEntrega=42, empresaID=3, sucursalID=1, tipoEntrega="domicilio", estadoEntregaID=1)


def _base_auth(rol, esGlobalJoin=False):
    return SimpleNamespace(login="user1", nombre="Usuario", empresaID=3, sucursalID=1, rol=rol, userID=9, esGlobalJoin=esGlobalJoin, roles=[])


def test_tomar_entrega_bloquea_domiciliario_si_flag_apagado(monkeypatch):
    auth = _base_auth("Domiciliario")
    db = _FakeDb(config=None)

    monkeypatch.setattr(domicilios_router, "_assert_auth_domiciliario", lambda db_arg, auth_arg: 55)
    monkeypatch.setattr(domicilios_router, "_locked_current_entrega", lambda db_arg, empresa_id, entrega_id: FAKE_ENTREGA)

    with pytest.raises(HTTPException) as exc_info:
        domicilios_router.tomar_entrega(42, TomarEntregaRequest(usuarioCambio="user1"), db=db, auth=auth)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "DOMICILIO_AUTOASIGNACION_DESHABILITADA"


def test_tomar_entrega_permite_domiciliario_si_flag_activo(monkeypatch):
    auth = _base_auth("Domiciliario")
    config = EmpresaConfiguracionAsignacion(empresaID=3, asignacionDomicilioActiva=True)
    db = _FakeDb(config=config)

    monkeypatch.setattr(domicilios_router, "_assert_auth_domiciliario", lambda db_arg, auth_arg: 55)
    monkeypatch.setattr(domicilios_router, "_locked_current_entrega", lambda db_arg, empresa_id, entrega_id: FAKE_ENTREGA)
    monkeypatch.setattr(
        domicilios_router.domicilio_service, "is_store_pickup_tipo_entrega",
        lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("continuo mas alla del gate, como se esperaba"))
    )

    with pytest.raises(RuntimeError, match="continuo mas alla del gate"):
        domicilios_router.tomar_entrega(42, TomarEntregaRequest(usuarioCambio="user1"), db=db, auth=auth)


def test_tomar_entrega_admin_no_depende_del_flag(monkeypatch):
    auth = _base_auth("Admin")
    db = _FakeDb(config=None)  # flag apagado/inexistente, pero el admin no depende de el

    monkeypatch.setattr(domicilios_router, "_assert_auth_domiciliario", lambda db_arg, auth_arg: 55)
    monkeypatch.setattr(domicilios_router, "_locked_current_entrega", lambda db_arg, empresa_id, entrega_id: FAKE_ENTREGA)
    monkeypatch.setattr(
        domicilios_router.domicilio_service, "is_store_pickup_tipo_entrega",
        lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("continuo mas alla del gate, como se esperaba"))
    )

    with pytest.raises(RuntimeError, match="continuo mas alla del gate"):
        domicilios_router.tomar_entrega(42, TomarEntregaRequest(usuarioCambio="user1"), db=db, auth=auth)
