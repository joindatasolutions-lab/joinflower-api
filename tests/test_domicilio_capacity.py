import pytest
from fastapi import HTTPException

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
