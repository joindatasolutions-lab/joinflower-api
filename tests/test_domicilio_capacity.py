import pytest
from fastapi import HTTPException
from datetime import datetime
from types import SimpleNamespace

from app.routers import domicilios as domicilios_router
from app.services import domicilio_service


def test_domicilio_capacity_default_disables_limit(monkeypatch):
    monkeypatch.delenv("DOMICILIO_MAX_TAREAS_ACTIVAS", raising=False)
    monkeypatch.setattr(domicilio_service, "count_entregas_activas", lambda *args, **kwargs: 999)

    domicilio_service.assert_domiciliario_capacity(
        db=None,
        empresa_id=3,
        sucursal_id=3,
        domiciliario_id=100,
    )


def test_domicilio_capacity_env_limit_still_blocks(monkeypatch):
    monkeypatch.setenv("DOMICILIO_MAX_TAREAS_ACTIVAS", "3")
    monkeypatch.setattr(domicilio_service, "count_entregas_activas", lambda *args, **kwargs: 3)

    with pytest.raises(HTTPException) as exc:
        domicilio_service.assert_domiciliario_capacity(
            db=None,
            empresa_id=3,
            sucursal_id=3,
            domiciliario_id=100,
        )

    assert exc.value.status_code == 400
    assert "limite permitido es 3" in str(exc.value.detail)


def test_domicilio_capacity_zero_disables_limit(monkeypatch):
    monkeypatch.setenv("DOMICILIO_MAX_TAREAS_ACTIVAS", "0")
    monkeypatch.setattr(domicilio_service, "count_entregas_activas", lambda *args, **kwargs: 999)

    domicilio_service.assert_domiciliario_capacity(
        db=None,
        empresa_id=3,
        sucursal_id=3,
        domiciliario_id=100,
    )


def test_domicilio_contadores_counts_disponibles_without_location_joins(monkeypatch):
    captured: dict[str, object] = {}

    class FakeQuery:
        def join(self, *_args, **_kwargs):
            return self

        def filter(self, *_args, **_kwargs):
            return self

        def order_by(self, *_args, **_kwargs):
            return self

        def count(self):
            return 0

    class FakeDb:
        def query(self, *_args, **_kwargs):
            return FakeQuery()

    def fake_sin_asignar_query(**kwargs):
        captured.update(kwargs)
        return FakeQuery()

    monkeypatch.setattr(
        domicilios_router,
        "_latest_entrega_id_subquery",
        lambda *_args, **_kwargs: SimpleNamespace(c=SimpleNamespace(entrega_id=1)),
    )
    monkeypatch.setattr(domicilio_service, "resolve_estado_entrega_id", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(domicilios_router, "_build_pedidos_sin_asignar_query", fake_sin_asignar_query)

    domicilios_router._domicilio_contadores(
        db=FakeDb(),
        empresa_id=3,
        sucursal_id=3,
        domiciliario_id=100,
        fecha_desde=datetime(2026, 7, 16, 0, 0, 0),
        fecha_hasta=datetime(2026, 7, 16, 23, 59, 59),
    )

    assert captured["include_location"] is False
