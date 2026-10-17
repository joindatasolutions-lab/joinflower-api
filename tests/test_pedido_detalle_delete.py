from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.routers import pedido as router


@pytest.mark.parametrize("production_state", [1, 5])
def test_delete_detaches_production_before_deleting_detail(monkeypatch, production_state):
    pedido = SimpleNamespace(idPedido=6689, empresaID=3, clienteID=10, estadoPedidoID=1, version=7)
    detalle = SimpleNamespace(idPedidoDetalle=7065)
    production = SimpleNamespace(
        pedidoDetalleID=7065, estado=production_state,
        observacionesInternas="Original", updatedAt=None,
    )
    db = MagicMock()
    order_query, detail_query, count_query, production_query, client_query = [MagicMock() for _ in range(5)]
    order_query.filter.return_value.with_for_update.return_value.populate_existing.return_value.first.return_value = pedido
    detail_query.filter.return_value.first.return_value = detalle
    count_query.filter.return_value.scalar.return_value = 2
    production_query.filter.return_value.all.return_value = [production]
    client_query.filter.return_value.first.return_value = None
    db.query.side_effect = [order_query, detail_query, count_query, production_query, client_query]
    monkeypatch.setattr(router, "assert_same_empresa", lambda *args: None)
    monkeypatch.setattr(router, "_estado_pedido_nombre", lambda *args: "APROBADO")
    monkeypatch.setattr(router.produccion_service, "estado_produccion_id", lambda *args: 5)
    transition = MagicMock(return_value=True)
    monkeypatch.setattr(router.produccion_service, "transicion_produccion_permitida", transition)
    recalculate = MagicMock()
    payments = MagicMock()
    monkeypatch.setattr(router, "_recalculate_pedido_financials", recalculate)
    monkeypatch.setattr(router, "_sync_existing_pago_total", payments)

    def delete(row):
        assert row is detalle
        assert production.pedidoDetalleID is None
        assert production.estado == 5
        assert db.flush.call_count >= 1

    db.delete.side_effect = delete
    result = router.eliminar_detalle_pedido(6689, 7065, version=7, db=db, auth=SimpleNamespace(empresaID=3, userID=4))

    assert result == {"status": "ok", "version": 8, "pedidoID": 6689, "detalleID": 7065}
    assert production.observacionesInternas.startswith("Original")
    assert transition.call_count == (0 if production_state == 5 else 1)
    recalculate.assert_called_once()
    payments.assert_called_once()
    db.commit.assert_called_once()
    db.rollback.assert_not_called()
