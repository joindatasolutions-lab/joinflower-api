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

    def count(self):
        return self.value


class _FakeDb:
    def query(self, *args, **kwargs):
        return _ScalarQuery(0)

    def commit(self):
        return None


def test_listar_produccion_allows_overdue_unassigned_items_for_florista(monkeypatch):
    auth = SimpleNamespace(
        login="florista1",
        nombre="Elibeth Salgado",
        empresaID=3,
        sucursalID=3,
        rol="Florista",
        userID=12,
        esGlobalJoin=False,
    )
    db = _FakeDb()
    captured: dict[str, object] = {}

    monkeypatch.setattr(produccion_router, "_current_florista_for_user", lambda db_arg, auth_arg: object())
    monkeypatch.setattr(produccion_router.produccion_service, "estado_produccion_id", lambda db_arg, estado: 1)
    monkeypatch.setattr(
        produccion_router.produccion_service,
        "asignar_pendientes_por_fecha",
        lambda **kwargs: {"evaluadas": 0, "asignadas": 0, "sinDisponibilidad": 0},
    )

    def fake_build_items(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(produccion_router, "_build_items", fake_build_items)

    produccion_router.listar_produccion(
        empresa_id=3,
        sucursal_id=3,
        fecha=date(2026, 5, 13),
        estado=None,
        todas_fechas=False,
        incluir_cancelado=False,
        auto_asignar_pendientes_hoy=False,
        db=db,
        auth=auth,
    )

    assert captured["empresa_id"] == 3
    assert captured["sucursal_id"] == 3
    assert captured["fecha_programada"] == date(2026, 5, 13)
    assert captured["include_overdue_unassigned"] is True


def test_listar_produccion_keeps_exact_date_filter_for_admin(monkeypatch):
    auth = SimpleNamespace(
        login="flora.admin",
        nombre="Flora Admin",
        empresaID=3,
        sucursalID=3,
        rol="Admin",
        userID=99,
        esGlobalJoin=False,
    )
    db = _FakeDb()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        produccion_router.produccion_service,
        "asignar_pendientes_por_fecha",
        lambda **kwargs: {"evaluadas": 0, "asignadas": 0, "sinDisponibilidad": 0},
    )
    monkeypatch.setattr(produccion_router.produccion_service, "estado_produccion_id", lambda db_arg, estado: 1)

    def fake_build_items(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(produccion_router, "_build_items", fake_build_items)

    produccion_router.listar_produccion(
        empresa_id=3,
        sucursal_id=3,
        fecha=date(2026, 5, 13),
        estado=None,
        todas_fechas=False,
        incluir_cancelado=False,
        auto_asignar_pendientes_hoy=False,
        db=db,
        auth=auth,
    )

    assert captured["include_overdue_unassigned"] is False
