from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import literal
from app.models.pedido import Pedido
from app.models.estadopedido import EstadoPedido
from app.routers import pedido as router
from test_sql_order_pagination import db


def test_statistics_use_colombia_day_and_all_filtered_orders(db, monkeypatch):
    monkeypatch.setattr(router, "_factura_impresa_condition", lambda: literal(False))
    db.add_all([EstadoPedido(idEstadoPedido=2, nombreEstado=" PENDIENTE "), EstadoPedido(idEstadoPedido=3, nombreEstado="CANCELADO")])
    orders = db.query(Pedido).filter(Pedido.empresaID == 1).order_by(Pedido.idPedido).all()
    orders[0].fechaPedido = datetime(2026, 9, 1, 23, 59, 59)
    orders[1].fechaPedido = datetime(2026, 9, 2, 0)
    orders[1].totalIva = Decimal("19")
    orders[2].fechaPedido = datetime(2026, 9, 2, 23, 59, 59)
    orders[2].estadoPedidoID = 2
    orders[3].fechaPedido = datetime(2026, 9, 3, 0)
    orders[4].fechaPedido = datetime(2026, 9, 2, 12)
    orders[4].estadoPedidoID = 3
    db.flush()
    query = db.query(Pedido).outerjoin(EstadoPedido).filter(Pedido.empresaID == 1)
    total, kpis, _ = router._pedido_list_statistics(query, fecha_hoy=date(2026, 9, 2))
    assert total == 5
    assert kpis.ventaHoy == 119
    assert kpis.pedidosHoy == 2
    assert (kpis.aprobados, kpis.pendientes, kpis.cancelados, kpis.sinImprimir) == (3, 1, 1, 3)
    total, empty, _ = router._pedido_list_statistics(query.filter(Pedido.sucursalID == 999), fecha_hoy=date(2026, 9, 2))
    assert total == 0
    assert all(value == 0 for value in empty.model_dump().values())


@pytest.mark.parametrize("total, allowed", [(100, True), (99, False), (0, False)])
def test_mixed_payment_approval_uses_supplied_total_without_queries(total, allowed):
    class NoQueries:
        def query(self, *args):
            raise AssertionError("Unexpected per-order query")
    result = router._approval_gate_summary(
        NoQueries(), pedido_id=1, empresa_id=1,
        rules={"require_payment_before_approval": True, "require_sales_channel_before_approval": False},
        pago_resumen={"metodosPago": ["Efectivo", "Tarjeta"], "canalFlora": None,
                      "detallePago": [{"metodo": "Efectivo", "monto": 40}, {"metodo": "Tarjeta", "monto": 60}]},
        total_pedido=Decimal(total),
    )
    assert result["puedeAprobar"] is allowed


def test_pedido_router_has_no_schema_creation():
    import inspect
    source = inspect.getsource(router)
    assert "CREATE TABLE" not in source
    assert "CREATE INDEX" not in source
