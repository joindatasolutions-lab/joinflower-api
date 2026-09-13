import pytest
from pydantic import ValidationError

from app.routers import auth as auth_router
from app.schemas.auth import EmpresaCreateRequest, EmpresaUpdateRequest


def test_empresa_create_allows_missing_nit():
    payload = EmpresaCreateRequest(nombreComercial="Floreria Demo")

    assert payload.nit is None


def test_empresa_create_validates_responsable_email_when_present():
    with pytest.raises(ValidationError):
        EmpresaCreateRequest(
            nombreComercial="Floreria Demo",
            correoResponsable="correo-invalido",
        )


def test_empresa_update_validates_responsable_email_when_present():
    with pytest.raises(ValidationError):
        EmpresaUpdateRequest(correoResponsable="correo-invalido")


def test_crear_empresa_core_uses_injected_auth_context():
    names = auth_router._crear_empresa_core.__code__.co_names
    variables = auth_router._crear_empresa_core.__code__.co_varnames

    assert "auth" in variables
    assert "_auth" not in names

