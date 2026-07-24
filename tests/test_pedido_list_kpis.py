from decimal import Decimal

from app.routers.pedido import _build_pedido_list_kpis


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *_args, **_kwargs):
        return self

    def all(self):
        return self.rows


class FakeDb:
    def __init__(self, rows):
        self.rows = rows

    def query(self, *_args, **_kwargs):
        return FakeQuery(self.rows)


def test_pedido_list_kpis_are_calculated_from_all_filtered_candidates():
    pedido_rows = [
        (pedido_id, Decimal("100.00"), Decimal("0.00"))
        for pedido_id in range(1, 52)
    ]
    estado_map = {pedido_id: "APROBADO" for pedido_id in range(1, 46)}
    estado_map.update(
        {
            46: "CREADO",
            47: "PENDIENTE",
            48: "CANCELADO",
            49: "RECHAZADO",
            50: "CANCELADO",
            51: "RECHAZADO",
        }
    )

    kpis = _build_pedido_list_kpis(
        db=FakeDb(pedido_rows),
        empresa_id=3,
        pedido_ids=list(range(1, 52)),
        estado_map=estado_map,
        facturas_pendientes_impresion=7,
    )

    assert kpis.pedidosHoy == 47
    assert kpis.cancelados == 4
    assert kpis.aprobados == 45
    assert kpis.pendientes == 2
    assert kpis.sinImprimir == 7
    assert kpis.ventaHoy == 4500.0
