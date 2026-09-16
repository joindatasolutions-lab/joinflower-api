"""Verifica _combinar_lineas_producto_duplicadas: el formulario de pedido manual permite
agregar el mismo producto en varias lineas (p.ej. con precios distintos por
personalizacion), pero petalops.pedido_detalle tiene UNIQUE(pedido_id, producto_id) --
insertar dos filas para el mismo producto en el mismo pedido revienta con un
UniqueViolation. Estas lineas deben combinarse en una sola antes de insertar.
"""
from decimal import Decimal

from app.routers.pedido import _combinar_lineas_producto_duplicadas


def _fallback_no_deberia_llamarse(producto_id):
    raise AssertionError("no deberia necesitar fallback si todas las lineas traen precio")


def test_sin_duplicados_no_cambia_nada():
    productos = [
        {"productoID": 1, "cantidad": Decimal("2"), "precio": Decimal("5000.00"), "observaciones": None},
        {"productoID": 2, "cantidad": Decimal("1"), "precio": Decimal("3000.00"), "observaciones": "sin tarjeta"},
    ]
    resultado = _combinar_lineas_producto_duplicadas(productos, resolver_precio_fallback=_fallback_no_deberia_llamarse)
    assert resultado == productos


def test_combina_caso_real_del_error_en_produccion():
    # Mismo caso reportado por Maria C Floristeria: producto 541 en 3 lineas con
    # precios distintos (20000, 10000, 10000), cantidad 1 cada una.
    productos = [
        {"productoID": 541, "cantidad": Decimal("1"), "precio": Decimal("20000.00"), "observaciones": None},
        {"productoID": 541, "cantidad": Decimal("1"), "precio": Decimal("10000.00"), "observaciones": None},
        {"productoID": 541, "cantidad": Decimal("1"), "precio": Decimal("10000.00"), "observaciones": None},
    ]
    resultado = _combinar_lineas_producto_duplicadas(productos, resolver_precio_fallback=_fallback_no_deberia_llamarse)

    assert len(resultado) == 1
    linea = resultado[0]
    assert linea["productoID"] == 541
    assert linea["cantidad"] == Decimal("3")
    # precio_unitario = promedio ponderado (40000.00 / 3 = 13333.33 redondeado). Al
    # multiplicar de vuelta por cantidad queda a 1 centavo del monto original exacto --
    # inevitable al representar 3 unidades a precios distintos como una sola tarifa unitaria.
    assert linea["precio"] == Decimal("13333.33")
    assert abs((linea["precio"] * linea["cantidad"]).quantize(Decimal("0.01")) - Decimal("40000.00")) <= Decimal("0.01")


def test_combina_y_concatena_observaciones_sin_duplicar():
    productos = [
        {"productoID": 7, "cantidad": Decimal("1"), "precio": Decimal("15000.00"), "observaciones": "sin tarjeta"},
        {"productoID": 7, "cantidad": Decimal("2"), "precio": Decimal("15000.00"), "observaciones": "entregar en la manana"},
        {"productoID": 7, "cantidad": Decimal("1"), "precio": Decimal("15000.00"), "observaciones": "sin tarjeta"},
    ]
    resultado = _combinar_lineas_producto_duplicadas(productos, resolver_precio_fallback=_fallback_no_deberia_llamarse)

    assert len(resultado) == 1
    linea = resultado[0]
    assert linea["cantidad"] == Decimal("4")
    assert linea["observaciones"] == "sin tarjeta; entregar en la manana"


def test_usa_fallback_cuando_una_linea_no_trae_precio():
    productos = [
        {"productoID": 9, "cantidad": Decimal("1"), "precio": Decimal("12000.00"), "observaciones": None},
        {"productoID": 9, "cantidad": Decimal("1"), "precio": None, "observaciones": None},
    ]
    resultado = _combinar_lineas_producto_duplicadas(
        productos, resolver_precio_fallback=lambda producto_id: Decimal("8000.00")
    )

    assert len(resultado) == 1
    linea = resultado[0]
    assert linea["cantidad"] == Decimal("2")
    # (12000 + 8000) / 2 = 10000.00
    assert linea["precio"] == Decimal("10000.00")


def test_no_mezcla_productos_distintos():
    productos = [
        {"productoID": 1, "cantidad": Decimal("1"), "precio": Decimal("5000.00"), "observaciones": None},
        {"productoID": 2, "cantidad": Decimal("1"), "precio": Decimal("6000.00"), "observaciones": None},
        {"productoID": 1, "cantidad": Decimal("1"), "precio": Decimal("5000.00"), "observaciones": None},
    ]
    resultado = _combinar_lineas_producto_duplicadas(productos, resolver_precio_fallback=_fallback_no_deberia_llamarse)

    por_producto = {linea["productoID"]: linea for linea in resultado}
    assert len(resultado) == 2
    assert por_producto[1]["cantidad"] == Decimal("2")
    assert por_producto[2]["cantidad"] == Decimal("1")
