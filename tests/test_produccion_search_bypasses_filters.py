from datetime import date
from types import SimpleNamespace

from app.routers import produccion as produccion_router


class _ScalarQuery:
    def __init__(self, value):
        self.value = value

    def filter(self, *args, **kwargs):
        return self

    def scalar(self):
        return self.value


class _FakeDb:
    def __init__(self, scalar_value=0):
        self.scalar_value = scalar_value

    def query(self, *args, **kwargs):
        return _ScalarQuery(self.scalar_value)

    def commit(self):
        return None


def test_listar_produccion_search_ignores_fecha_y_estado_and_returns_metricas(monkeypatch):
    auth = SimpleNamespace(
        login="flora.admin",
        nombre="Flora Admin",
        empresaID=3,
        sucursalID=3,
        rol="Admin",
        userID=99,
        esGlobalJoin=False,
    )
    db = _FakeDb(scalar_value=7)
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        produccion_router.produccion_service,
        "asignar_pendientes_por_fecha",
        lambda **kwargs: {"evaluadas": 0, "asignadas": 0, "sinDisponibilidad": 0},
    )
    monkeypatch.setattr(
        produccion_router.produccion_service,
        "estado_produccion_id",
        lambda db_arg, estado: 1 if str(estado).lower() == "pendiente" else 4,
    )

    def fake_build_items(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(produccion_router, "_build_items", fake_build_items)

    response = produccion_router.listar_produccion(
        empresa_id=3,
        sucursal_id=3,
        fecha=date(2026, 5, 13),
        estado="Pendiente",
        q="95447",
        incluir_cancelado=False,
        auto_asignar_pendientes_hoy=False,
        db=db,
        auth=auth,
    )

    assert captured["fecha_programada"] == date(2026, 5, 13)
    assert captured["estado"] == "Pendiente"
    assert captured["search_q"] == "95447"
    assert response.metricas is not None
    assert response.metricas.pendientesFuturos == 7
