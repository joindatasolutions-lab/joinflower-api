from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from app.routers.pedido import _build_ventas_diario_rows
from app.routers.pedido import router


def _pedido(
    pedido_id,
    fecha,
    estado,
    *,
    total_bruto,
    total_iva=0,
    costo_domicilio=0,
):
    pedido = SimpleNamespace(
        idPedido=pedido_id,
        fechaPedido=fecha,
        totalBruto=Decimal(str(total_bruto)),
        totalIva=Decimal(str(total_iva)),
        costoDomicilio=Decimal(str(costo_domicilio)),
    )
    estado_obj = SimpleNamespace(nombreEstado=estado)
    return pedido, estado_obj


def test_ventas_diario_uses_approved_orders_and_charged_delivery_only():
    rows = [
        _pedido(1, datetime(2026, 8, 8, 9, 0), "APROBADO", total_bruto=100000, costo_domicilio=10000),
        _pedido(2, datetime(2026, 8, 8, 10, 0), "APROBADO", total_bruto=50000, total_iva=9500, costo_domicilio=0),
        _pedido(3, datetime(2026, 8, 8, 11, 0), "ENTREGADO", total_bruto=200000, costo_domicilio=12000),
        _pedido(4, datetime(2026, 8, 9, 9, 0), "APROBADO", total_bruto=70000, costo_domicilio=8000),
    ]
    pagos = {
        1: {"recargoLinkMonto": 3000, "descuentoMonto": 1000, "saldoFavorMonto": 0},
        2: {"recargoLinkMonto": 0, "descuentoMonto": 500, "saldoFavorMonto": 2000},
        3: {"recargoLinkMonto": 9000, "descuentoMonto": 0, "saldoFavorMonto": 0},
    }

    result = _build_ventas_diario_rows(rows, pagos)

    assert result["orderRows"] == [
        {
            "fecha": "2026-08-08",
            "cantidadPedidos": 2,
            "totalArreglos": 159500.0,
            "totalDomicilios": 10000.0,
            "totalRecargos": 3000.0,
            "totalDescuentos": 1500.0,
            "totalSaldoFavor": 2000.0,
            "totalVenta": 173000.0,
        },
        {
            "fecha": "2026-08-09",
            "cantidadPedidos": 1,
            "totalArreglos": 70000.0,
            "totalDomicilios": 8000.0,
            "totalRecargos": 0.0,
            "totalDescuentos": 0.0,
            "totalSaldoFavor": 0.0,
            "totalVenta": 78000.0,
        },
    ]
    assert result["totals"]["cantidadPedidos"] == 3
    assert result["totals"]["totalDomicilios"] == 18000.0


def test_ventas_diario_registers_legacy_and_canonical_paths():
    paths = {getattr(route, "path", None) for route in router.routes}

    assert "/contabilidad/ventas-diario" in paths
    assert "/pedidos/contabilidad/ventas-diario" in paths
