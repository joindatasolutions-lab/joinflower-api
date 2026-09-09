"""Pruebas de GET/PUT /configuracion/empresas/{id}/asignacion (flag "Acciones": permite
autoasignacion de pedidos en Produccion y de domicilios en Domicilios, por empresa).

Usa una sesion falsa (sin base de datos real) para poder ejercitar la logica real del
router sin depender de Postgres.
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.empresa_configuracion_asignacion import EmpresaConfiguracionAsignacion
from app.routers import configuracion as configuracion_router
from app.schemas.configuracion import ConfiguracionAsignacionUpdateRequest


class FakeQuery:
    def __init__(self, results):
        self._results = list(results)

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._results[0] if self._results else None


class FakeSession:
    def __init__(self, config=None):
        self._config = config
        self.commits = 0
        self.added = []

    def query(self, model):
        assert model is EmpresaConfiguracionAsignacion
        return FakeQuery([self._config] if self._config else [])

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1

    def refresh(self, obj):
        pass


FAKE_AUTH_TENANT = SimpleNamespace(userID=1, login="admin", empresaID=999, rol="Admin", esGlobalJoin=False, roles=[])
FAKE_AUTH_OTHER_EMPRESA = SimpleNamespace(userID=2, login="admin2", empresaID=1, rol="Admin", esGlobalJoin=False, roles=[])


def test_obtener_configuracion_sin_fila_retorna_ambos_flags_activos_por_defecto():
    # Opt-out, no opt-in: sin fila de configuracion, la autoasignacion sigue activa como
    # ya lo estaba antes de que este flag existiera. El admin la desactiva explicitamente.
    db = FakeSession(config=None)

    resultado = configuracion_router.obtener_configuracion_asignacion(
        empresa_id=999, db=db, auth=FAKE_AUTH_TENANT
    )

    assert resultado.empresaID == 999
    assert resultado.asignacionProduccionActiva is True
    assert resultado.asignacionDomicilioActiva is True


def test_obtener_configuracion_con_fila_desactivada_respeta_el_apagado():
    config = EmpresaConfiguracionAsignacion(
        empresaID=999, asignacionProduccionActiva=False, asignacionDomicilioActiva=False
    )
    db = FakeSession(config=config)

    resultado = configuracion_router.obtener_configuracion_asignacion(
        empresa_id=999, db=db, auth=FAKE_AUTH_TENANT
    )

    assert resultado.asignacionProduccionActiva is False
    assert resultado.asignacionDomicilioActiva is False


def test_obtener_configuracion_con_fila_retorna_valores_reales():
    config = EmpresaConfiguracionAsignacion(
        empresaID=999, asignacionProduccionActiva=True, asignacionDomicilioActiva=False
    )
    db = FakeSession(config=config)

    resultado = configuracion_router.obtener_configuracion_asignacion(
        empresa_id=999, db=db, auth=FAKE_AUTH_TENANT
    )

    assert resultado.asignacionProduccionActiva is True
    assert resultado.asignacionDomicilioActiva is False


def test_obtener_configuracion_de_otra_empresa_rechaza_acceso():
    db = FakeSession(config=None)

    with pytest.raises(HTTPException) as exc_info:
        configuracion_router.obtener_configuracion_asignacion(
            empresa_id=999, db=db, auth=FAKE_AUTH_OTHER_EMPRESA
        )

    assert exc_info.value.status_code == 403


def test_actualizar_configuracion_crea_fila_si_no_existe():
    db = FakeSession(config=None)
    payload = ConfiguracionAsignacionUpdateRequest(asignacionProduccionActiva=False)

    resultado = configuracion_router.actualizar_configuracion_asignacion(
        empresa_id=999, payload=payload, db=db, auth=FAKE_AUTH_TENANT
    )

    assert len(db.added) == 1
    assert db.added[0].asignacionProduccionActiva is False
    # El campo no enviado arranca activo por defecto (misma convencion que el GET).
    assert db.added[0].asignacionDomicilioActiva is True
    assert resultado.asignacionProduccionActiva is False
    assert db.commits == 1


def test_actualizar_configuracion_reutiliza_fila_existente_sin_crear_otra():
    config = EmpresaConfiguracionAsignacion(
        empresaID=999, asignacionProduccionActiva=False, asignacionDomicilioActiva=False
    )
    db = FakeSession(config=config)
    payload = ConfiguracionAsignacionUpdateRequest(asignacionDomicilioActiva=True)

    resultado = configuracion_router.actualizar_configuracion_asignacion(
        empresa_id=999, payload=payload, db=db, auth=FAKE_AUTH_TENANT
    )

    assert len(db.added) == 0
    assert config.asignacionDomicilioActiva is True
    assert config.asignacionProduccionActiva is False  # no enviado, no se toca
    assert resultado.asignacionDomicilioActiva is True


def test_actualizar_configuracion_solo_cambia_campo_enviado():
    config = EmpresaConfiguracionAsignacion(
        empresaID=999, asignacionProduccionActiva=True, asignacionDomicilioActiva=True
    )
    db = FakeSession(config=config)
    payload = ConfiguracionAsignacionUpdateRequest(asignacionProduccionActiva=False)

    configuracion_router.actualizar_configuracion_asignacion(
        empresa_id=999, payload=payload, db=db, auth=FAKE_AUTH_TENANT
    )

    assert config.asignacionProduccionActiva is False
    assert config.asignacionDomicilioActiva is True  # no enviado, se conserva
