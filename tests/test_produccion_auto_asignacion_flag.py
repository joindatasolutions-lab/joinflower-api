"""Verifica _debe_autoasignar_pendientes_hoy: el interruptor "Autoasignacion automatica"
de Produccion (auto_asignacion_produccion_activa), separado del boton manual "Asignar".
"""
from datetime import date

from app.models.empresa_configuracion_asignacion import EmpresaConfiguracionAsignacion
from app.routers import produccion as produccion_router

TODAY = date(2026, 5, 10)


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


def _call(db, **overrides):
    params = dict(
        empresa_id=3,
        auto_asignar_pendientes_hoy=True,
        metric_filter=None,
        q=None,
        target_fecha=TODAY,
        today=TODAY,
    )
    params.update(overrides)
    return produccion_router._debe_autoasignar_pendientes_hoy(db, **params)


def test_sin_fila_autoasigna_por_defecto():
    assert _call(_FakeDb(config=None)) is True


def test_fila_con_flag_activo_autoasigna():
    config = EmpresaConfiguracionAsignacion(empresaID=3, autoAsignacionProduccionActiva=True)
    assert _call(_FakeDb(config=config)) is True


def test_fila_con_flag_apagado_no_autoasigna():
    config = EmpresaConfiguracionAsignacion(empresaID=3, autoAsignacionProduccionActiva=False)
    assert _call(_FakeDb(config=config)) is False


def test_no_autoasigna_si_el_caller_no_lo_pide():
    db = _FakeDb(config=None)
    assert _call(db, auto_asignar_pendientes_hoy=False) is False


def test_no_autoasigna_con_metric_filter_activo():
    db = _FakeDb(config=None)
    assert _call(db, metric_filter="sinAsignar") is False


def test_no_autoasigna_con_busqueda_activa():
    db = _FakeDb(config=None)
    assert _call(db, q="Rosa") is False


def test_no_autoasigna_si_la_fecha_objetivo_no_es_hoy():
    db = _FakeDb(config=None)
    assert _call(db, target_fecha=date(2026, 5, 9)) is False
