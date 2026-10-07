import pytest
from fastapi import HTTPException

from app.core.security import assert_same_empresa, require_admin_role, require_module_access
from app.routers.configuracion import require_order_catalog_read
from app.schemas.auth import AuthContext


def order_user(*, access=True, plan=True):
    return AuthContext(
        userID=2, empresaID=3, rolID=2, rol="Vendedor", nombre="Vendedor",
        login="vendedor", email="vendedor@example.com",
        permisos={
            "pedidos": {"puedeVer": access, "puedeCrear": False, "puedeEditar": False, "puedeEliminar": False},
            "contabilidad": {"puedeVer": True, "puedeEditar": False},
        },
        modulosActivosPlan={"pedidos", "contabilidad"} if plan else {"contabilidad"},
    )


@pytest.mark.parametrize("action", ["puedeVer", "puedeCrear", "puedeEditar", "puedeEliminar"])
def test_module_access_grants_every_order_operation(action):
    auth = order_user()
    assert require_module_access("pedidos", action)(auth) is auth
    exposed = {item["modulo"]: item for item in auth.to_me_response()["permisos"]}
    assert exposed["pedidos"][action] is True


@pytest.mark.parametrize("action", ["puedeVer", "puedeCrear", "puedeEditar", "puedeEliminar"])
@pytest.mark.parametrize("access,plan", [(False, True), (True, False)])
def test_order_operations_require_access_and_active_plan(action, access, plan):
    with pytest.raises(HTTPException) as exc:
        require_module_access("pedidos", action)(order_user(access=access, plan=plan))
    assert exc.value.status_code == 403


def test_other_modules_keep_action_permissions():
    auth = order_user()
    with pytest.raises(HTTPException) as exc:
        require_module_access("contabilidad", "puedeEditar")(auth)
    assert exc.value.status_code == 403
    exposed = {item["modulo"]: item for item in auth.to_me_response()["permisos"]}
    assert exposed["contabilidad"]["puedeEditar"] is False


def test_order_access_does_not_allow_cross_company_or_configuration_edits():
    auth = order_user()
    assert require_order_catalog_read(auth) is auth
    assert_same_empresa(auth, 3)
    for check in (lambda: assert_same_empresa(auth, 4), lambda: require_admin_role(auth)):
        with pytest.raises(HTTPException) as exc:
            check()
        assert exc.value.status_code == 403


def test_catalog_read_requires_order_access():
    with pytest.raises(HTTPException) as exc:
        require_order_catalog_read(order_user(access=False))
    assert exc.value.status_code == 403
