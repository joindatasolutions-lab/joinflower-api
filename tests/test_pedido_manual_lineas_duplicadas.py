"""Verifica _nombres_productos_duplicados: el formulario de pedido manual permite agregar
el mismo producto en varias lineas separadas, pero petalops.pedido_detalle tiene
UNIQUE(pedido_id, producto_id) -- insertar dos filas para el mismo producto en el mismo
pedido revienta con un UniqueViolation. crear_pedido_manual debe rechazar el pedido con un
mensaje claro (en vez de un error crudo de base de datos) para que quien lo registra lo
corrija sumando la cantidad en una sola linea.
"""
from types import SimpleNamespace

from app.routers.pedido import _nombres_productos_duplicados


def _producto(nombre):
    return SimpleNamespace(nombreProducto=nombre)


def test_sin_duplicados_no_reporta_nada():
    productos = [
        {"productoID": 1, "cantidad": 2, "precio": None, "observaciones": None},
        {"productoID": 2, "cantidad": 1, "precio": None, "observaciones": None},
    ]
    productos_map = {1: _producto("Rosa roja"), 2: _producto("Girasol")}
    assert _nombres_productos_duplicados(productos, productos_map) == []


def test_detecta_producto_duplicado_caso_real_del_error_en_produccion():
    # Mismo caso reportado por Maria C Floristeria: producto 541 en 3 lineas separadas.
    productos = [
        {"productoID": 541, "cantidad": 1, "precio": 20000, "observaciones": None},
        {"productoID": 541, "cantidad": 1, "precio": 10000, "observaciones": None},
        {"productoID": 541, "cantidad": 1, "precio": 10000, "observaciones": None},
    ]
    productos_map = {541: _producto("Ramo Primavera")}
    assert _nombres_productos_duplicados(productos, productos_map) == ["Ramo Primavera"]


def test_detecta_varios_productos_duplicados_a_la_vez():
    productos = [
        {"productoID": 1, "cantidad": 1, "precio": None, "observaciones": None},
        {"productoID": 1, "cantidad": 1, "precio": None, "observaciones": None},
        {"productoID": 2, "cantidad": 1, "precio": None, "observaciones": None},
        {"productoID": 3, "cantidad": 1, "precio": None, "observaciones": None},
        {"productoID": 3, "cantidad": 1, "precio": None, "observaciones": None},
    ]
    productos_map = {1: _producto("Rosa roja"), 2: _producto("Girasol"), 3: _producto("Tulipan")}
    assert _nombres_productos_duplicados(productos, productos_map) == ["Rosa roja", "Tulipan"]


def test_usa_placeholder_si_el_producto_no_esta_en_el_mapa():
    productos = [
        {"productoID": 99, "cantidad": 1, "precio": None, "observaciones": None},
        {"productoID": 99, "cantidad": 1, "precio": None, "observaciones": None},
    ]
    assert _nombres_productos_duplicados(productos, {}) == ["#99"]
