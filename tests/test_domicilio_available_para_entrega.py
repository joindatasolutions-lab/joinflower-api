import inspect
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.produccion import Produccion
from app.routers import domicilios as domicilios_router


class FakeQuery:
    def __init__(self, first_value=None):
        self._first_value = first_value

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self._first_value


class FakeDb:
    def __init__(self, produccion):
        self.produccion = produccion

    def query(self, *entities):
        if entities == (Produccion,):
            return FakeQuery(first_value=self.produccion)
        raise AssertionError(f"Unexpected query entities: {entities}")


def test_available_queries_require_produccion_para_entrega():
    orm_disponibles = inspect.getsource(domicilios_router._build_pedidos_disponibles_query)
    orm_sin_asignar = inspect.getsource(domicilios_router._build_pedidos_sin_asignar_query)
    raw_api = inspect.getsource(domicilios_router._listar_pedidos_disponibles_api_rows)

    assert "Produccion.estado == estado_para_entrega" in orm_disponibles
    assert "Produccion.estado == estado_para_entrega" in orm_sin_asignar
    assert "pr.estado_produccion_id = :estado_para_entrega" in raw_api
    assert "estado_pendiente_id" in orm_sin_asignar


@pytest.mark.parametrize("estado_produccion_id", [1, 3, 5])
def test_direct_assignment_rejects_orders_not_para_entrega(monkeypatch, estado_produccion_id):
    monkeypatch.setattr(
        domicilios_router.produccion_service,
        "estado_produccion_id",
        lambda *_args, **_kwargs: 4,
    )
    pedido = SimpleNamespace(idPedido=20, empresaID=3)
    entrega = SimpleNamespace(produccionID=10)
    produccion = SimpleNamespace(idProduccion=10, pedidoID=20, empresaID=3, estado=estado_produccion_id)

    with pytest.raises(HTTPException) as exc:
        domicilios_router._assert_pedido_para_entrega(FakeDb(produccion), pedido, entrega)

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "DOMICILIO_PEDIDO_NOT_READY"


def test_direct_assignment_allows_only_para_entrega(monkeypatch):
    monkeypatch.setattr(
        domicilios_router.produccion_service,
        "estado_produccion_id",
        lambda *_args, **_kwargs: 4,
    )
    pedido = SimpleNamespace(idPedido=20, empresaID=3)
    entrega = SimpleNamespace(produccionID=10)
    produccion = SimpleNamespace(idProduccion=10, pedidoID=20, empresaID=3, estado=4)

    result = domicilios_router._assert_pedido_para_entrega(FakeDb(produccion), pedido, entrega)

    assert result is produccion
