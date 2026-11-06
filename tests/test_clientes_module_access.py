import pytest
from fastapi import HTTPException

from app.core.security import require_module_access
from app.main import app
from app.schemas.auth import AuthContext


def _clientes_user(*, puede_editar: bool = True) -> AuthContext:
    return AuthContext(
        userID=20,
        empresaID=9,
        sucursalID=9,
        rolID=20,
        rol="Pedidos",
        nombre="Atencion al cliente",
        login="atencion.clientes",
        email="atencion@example.com",
        permisos={
            "clientes": {
                "puedeVer": True,
                "puedeCrear": True,
                "puedeEditar": puede_editar,
                "puedeEliminar": False,
            },
            "pedidos": {
                "puedeVer": False,
                "puedeCrear": False,
                "puedeEditar": False,
                "puedeEliminar": False,
            },
        },
        modulosActivosPlan={"clientes"},
    )


def test_clientes_user_can_edit_without_pedidos_access():
    auth = _clientes_user()

    assert require_module_access("clientes", "puedeEditar")(auth) is auth


def test_clientes_edit_still_requires_explicit_edit_permission():
    with pytest.raises(HTTPException) as exc:
        require_module_access("clientes", "puedeEditar")(_clientes_user(puede_editar=False))

    assert exc.value.status_code == 403


def test_update_cliente_route_uses_clientes_edit_permission():
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/clientes/{cliente_id}"
        and "PUT" in getattr(route, "methods", set())
    )
    dependency = next(
        dependency.call
        for dependency in route.dependant.dependencies
        if getattr(dependency.call, "__name__", "") == "dependency"
    )
    closure_values = {cell.cell_contents for cell in dependency.__closure__ or ()}

    assert "clientes" in closure_values
    assert "puedeEditar" in closure_values
    assert "pedidos" not in closure_values
