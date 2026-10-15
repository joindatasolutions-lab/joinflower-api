import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.models.sucursal import Sucursal
from app.routers import domicilios


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    with engine.connect() as conn:
        conn.execute(text("ATTACH DATABASE ':memory:' AS petalops"))
        Sucursal.__table__.create(conn)
        conn.execute(text("INSERT INTO petalops.sucursal (id_sucursal, empresa_id, nombre_sucursal, estado) VALUES (10, 1, 'A', 'Activo'), (20, 2, 'B', 'Activo')"))
        conn.execute(text("CREATE TABLE petalops.pedido_detalle (id_pedido_detalle INTEGER, pedido_id INTEGER, empresa_id INTEGER, producto_id INTEGER, sucursal_id INTEGER, cantidad INTEGER)"))
        conn.execute(text("CREATE TABLE petalops.producto (id_producto INTEGER, empresa_id INTEGER, codigo_producto TEXT, codigo_catalogo TEXT, nombre_producto TEXT)"))
        conn.execute(text("CREATE TABLE petalops.producto_sucursal (producto_id INTEGER, sucursal_id INTEGER, imagen_url TEXT)"))
        conn.execute(text("INSERT INTO petalops.producto VALUES (1, 1, 'A', NULL, 'Propio'), (2, 2, 'B', NULL, 'Ajeno')"))
        conn.execute(text("INSERT INTO petalops.pedido_detalle VALUES (1, 100, 1, 1, 10, 1), (2, 200, 2, 2, 20, 1), (3, NULL, 2, 2, 20, 1), (4, 101, 1, 2, 20, 1)"))
        conn.execute(text("INSERT INTO petalops.producto_sucursal VALUES (1, 10, 'propia.jpg'), (2, 20, 'ajena.jpg')"))
        with Session(bind=conn) as session:
            yield session
    engine.dispose()


def test_product_helpers_exclude_foreign_orders_details_products_and_images(db, monkeypatch):
    monkeypatch.setattr(domicilios, "_mostrar_codigo_catalogo", lambda *args: False)
    result = domicilios._pedido_product_payload_map(db, 1, [100, 101, 200], {3: 300})
    assert set(result) == {100, 101}
    assert result[100]["imageUrl"] == "propia.jpg"
    assert "Propio" in result[100]["arreglo"]
    assert "Ajeno" not in str(result)
    assert result[101]["imageUrl"] is None


@pytest.mark.parametrize("branch", [20, 999])
def test_branch_from_other_company_or_missing_is_rejected(db, branch):
    with pytest.raises(HTTPException) as exc:
        domicilios._assert_sucursal_empresa(db, 1, branch)
    assert exc.value.status_code == 403


@pytest.mark.parametrize("branch", [10, None])
def test_own_branch_and_optional_filter_are_allowed(db, branch):
    domicilios._assert_sucursal_empresa(db, 1, branch)


@pytest.mark.parametrize("branch", [20, 999])
def test_shared_branch_guard_rejects_foreign_and_missing(db, branch):
    from app.core.tenant_scope import assert_sucursal_empresa
    with pytest.raises(HTTPException) as exc:
        assert_sucursal_empresa(db, 1, branch)
    assert exc.value.status_code == 403


def test_numbering_never_falls_back_to_foreign_branch(db):
    from app.services.pedido_service import generar_numeracion_pedido
    with pytest.raises(HTTPException) as exc:
        generar_numeracion_pedido(db, 1, 20)
    assert exc.value.status_code == 400


def test_production_time_excludes_foreign_details(db):
    from app.services.produccion_service import calcular_tiempo_estimado_pedido
    db.execute(text("INSERT INTO petalops.pedido_detalle VALUES (5, 100, 2, 2, 20, 99)"))
    assert calcular_tiempo_estimado_pedido(db, 100, 1) == 30


@pytest.mark.skip(reason="Pendiente del trabajo de aislamiento de inventario, excluido de esta entrega; inventario conserva origin/main.")
def test_recipe_product_cannot_read_foreign_product_or_branch(db, monkeypatch):
    from app.routers import inventario
    from app.routers.inventario import _producto_precio_imagen
    # SQLite no tiene information_schema; representar los campos nuevos de main.
    db.execute(text("ALTER TABLE petalops.producto ADD COLUMN coleccion TEXT"))
    db.execute(text("ALTER TABLE petalops.producto ADD COLUMN categoria_id INTEGER"))
    db.execute(text("CREATE TABLE petalops.categoria (id_categoria INTEGER, nombre TEXT)"))
    monkeypatch.setattr(inventario, "_has_column", lambda *args: True)
    db.execute(text("ALTER TABLE petalops.producto_sucursal ADD COLUMN precio NUMERIC"))
    assert _producto_precio_imagen(db, 2, 20, 1)["codigoProducto"] is None
    db.execute(text("INSERT INTO petalops.producto_sucursal VALUES (1, 20, 'foreign.jpg', 999)"))
    result = _producto_precio_imagen(db, 1, 20, 1)
    assert result["imagenUrl"] is None
    assert result["precioVenta"] is None


@pytest.mark.parametrize("endpoint", ["barrios", "caja", "produccion"])
def test_foreign_branch_rejected_before_endpoint_writes(db, endpoint):
    from types import SimpleNamespace
    from app.routers import barrios, contabilidad, produccion
    auth = SimpleNamespace(empresaID=1, esGlobalJoin=False, rol="Admin", login="admin")
    with pytest.raises(HTTPException) as exc:
        if endpoint == "barrios":
            barrios.create_barrio(SimpleNamespace(sucursalID=20), db=db, auth=auth)
        elif endpoint == "caja":
            contabilidad.guardar_cierre_caja(SimpleNamespace(empresaID=1, sucursalID=20), db=db, auth=auth)
        else:
            produccion.listar_produccion(empresa_id=1, sucursal_id=20, db=db, auth=auth)
    assert exc.value.status_code == 403
