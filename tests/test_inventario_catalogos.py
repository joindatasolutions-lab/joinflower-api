from fastapi.testclient import TestClient

from app.core.security import get_current_auth_context
from app.main import app
from app.schemas.auth import AuthContext


def _auth_context() -> AuthContext:
    return AuthContext(
        userID=10,
        empresaID=3,
        empresaNombre="Flora",
        empresaSlug="flora",
        sucursalID=3,
        rolID=20,
        planID=1,
        rol="Inventarista",
        nombre="Usuario Inventario",
        login="flora.inventario",
        email="flora.inventario@empresa3.local",
        esGlobalJoin=False,
        ultimoLogin=None,
        permisos={"inventario": {"puedeVer": True, "puedeCrear": True, "puedeEditar": True, "puedeEliminar": False}},
        modulosActivosPlan={"inventario"},
    )


def test_inventario_categorias_exposes_operational_catalogs():
    app.dependency_overrides[get_current_auth_context] = _auth_context
    client = TestClient(app)

    try:
        response = client.get("/inventario/categorias")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    categorias = {item["categoria"]: item for item in payload["items"]}

    assert {"FLORES", "BASES", "MATERIALES", "ADICIONALES"} <= set(categorias)
    assert "Tallo" in categorias["FLORES"]["unidades"]
    assert "Marchita" in categorias["FLORES"]["motivosDano"]
    assert "Box" in categorias["BASES"]["subcategorias"]
    assert "Chocolates" in categorias["ADICIONALES"]["subcategorias"]
