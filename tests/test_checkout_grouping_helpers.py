from types import SimpleNamespace

from app.services.pedido_service import _normalize_checkout_productos


def test_normalize_checkout_productos_preserves_single_order_lines_by_product():
    productos = [
        SimpleNamespace(productoID=10, cantidad=2),
        SimpleNamespace(productoID=11, cantidad=1),
        SimpleNamespace(productoID=10, cantidad=3),
    ]

    assert _normalize_checkout_productos(productos) == [
        {"productoID": 10, "cantidad": 5},
        {"productoID": 11, "cantidad": 1},
    ]


def test_normalize_checkout_productos_ignores_non_positive_quantities():
    productos = [
        SimpleNamespace(productoID=10, cantidad=0),
        SimpleNamespace(productoID=11, cantidad=-2),
    ]

    assert _normalize_checkout_productos(productos) == []
