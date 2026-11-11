from decimal import Decimal

from types import SimpleNamespace

from app.routers import inventario as inventario_router
from app.routers.inventario import _normalize_import_lookup, importar_inventario_excel
from app.schemas.inventario import InventarioImportRequest, InventarioImportResponse


def test_inventory_import_schema_accepts_normalized_excel_rows():
    payload = InventarioImportRequest(
        empresaID=3,
        categoria="Flores",
        items=[
            {
                "fila": 2,
                "codigo": "FL-001",
                "nombre": "Rosa roja",
                "proveedor": "Flores Áurea",
                "stockActual": "5",
                "stockMinimo": "2",
                "valorUnitario": "750",
                "costoPaquete": "15000",
                "precioVenta": "3000",
                "precioVentaPaquete": "18000",
            }
        ],
    )

    assert payload.items[0].valorUnitario == Decimal("750")
    assert payload.items[0].precioVentaPaquete == Decimal("18000")
    assert payload.crearProveedores is True


def test_inventory_import_lookup_ignores_case_accents_and_symbols():
    assert _normalize_import_lookup(" Flores ÁUREA ") == "floresaurea"
    assert _normalize_import_lookup("SUB-CATEGORÍA") == "subcategoria"


def test_inventory_import_response_reports_partial_rows():
    response = InventarioImportResponse(
        status="partial",
        totalFilas=3,
        creados=2,
        omitidos=1,
        proveedoresCreados=1,
        errores=[{"fila": 4, "codigo": "FL-002", "mensaje": "Código repetido"}],
    )

    assert response.creados + response.omitidos == response.totalFilas
    assert response.errores[0].fila == 4


class _QueryRows:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *_args, **_kwargs):
        return self

    def all(self):
        return self.rows


class _DuplicateImportDb:
    def __init__(self):
        self.query_results = [[], []]
        self.committed = False

    def query(self, *_args, **_kwargs):
        return _QueryRows(self.query_results.pop(0))

    def commit(self):
        self.committed = True

    def rollback(self):
        raise AssertionError("No debe hacer rollback al omitir duplicados validos")


def test_inventory_import_skips_duplicate_codes_before_writing(monkeypatch):
    monkeypatch.setattr(inventario_router, "assert_same_empresa", lambda *_args: None)
    monkeypatch.setattr(inventario_router, "_has_column", lambda *_args: True)
    monkeypatch.setattr(
        inventario_router,
        "_inventario_schema_flags",
        lambda _db: {
            "categoria": True,
            "marca": True,
            "vendible": True,
            "dias_vida_util": True,
            "observaciones": True,
            "precio_venta_paquete": True,
        },
    )
    monkeypatch.setattr(
        inventario_router,
        "_crear_item_inventario",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("No debe crear filas duplicadas")),
    )
    payload = InventarioImportRequest(
        empresaID=3,
        categoria="Flores",
        items=[
            {"fila": 2, "codigo": "FL-001", "nombre": "Rosa roja"},
            {"fila": 3, "codigo": "fl 001", "nombre": "Rosa rosada"},
        ],
    )
    db = _DuplicateImportDb()

    response = importar_inventario_excel(
        payload,
        db=db,
        auth=SimpleNamespace(empresaID=3, sucursalID=3, userID=10),
    )

    assert response.creados == 0
    assert response.omitidos == 2
    assert len(response.errores) == 2
    assert db.committed is True
