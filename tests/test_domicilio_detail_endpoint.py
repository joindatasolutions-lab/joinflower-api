from decimal import Decimal
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.cliente import Cliente
from app.models.entrega import Entrega
from app.models.pedido import Pedido
from app.models.pedidodetalle import PedidoDetalle
from app.models.producto import Producto
from app.routers import domicilios as domicilios_router


class FakeQuery:
    def __init__(self, first_value=None, all_value=None):
        self._first_value = first_value
        self._all_value = all_value or []

    def filter(self, *args, **kwargs):
        return self

    def outerjoin(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self._first_value

    def all(self):
        return self._all_value


class FakeDb:
    def __init__(self, entrega=None, pedido=None, cliente=None, detalles=None):
        self.entrega = entrega
        self.pedido = pedido
        self.cliente = cliente
        self.detalles = detalles or []

    def query(self, *entities):
        if entities == (Entrega,):
            return FakeQuery(first_value=self.entrega)
        if entities == (Pedido,):
            return FakeQuery(first_value=self.pedido)
        if entities == (Cliente,):
            return FakeQuery(first_value=self.cliente)
        if entities == (PedidoDetalle, Producto):
            return FakeQuery(all_value=self.detalles)
        raise AssertionError(f"Unexpected query entities: {entities}")


def test_obtener_detalle_domicilio_returns_items_with_images(monkeypatch):
    monkeypatch.setattr(domicilios_router, "_assert_entrega_actor_scope", lambda *args, **kwargs: None)

    entrega = SimpleNamespace(
        idEntrega=10,
        empresaID=3,
        pedidoID=20,
        mensaje="Feliz cumple",
        domiciliarioID=48,
    )
    pedido = SimpleNamespace(
        idPedido=20,
        empresaID=3,
        clienteID=30,
        numeroPedido=96412,
        codigoPedido="FLR-96412",
    )
    cliente = SimpleNamespace(idCliente=30, empresaID=3, nombreCompleto="Cliente Demo")
    detalle = SimpleNamespace(
        idPedidoDetalle=40,
        empresaID=3,
        pedidoID=20,
        productoID=50,
        cantidad=Decimal("2"),
    )
    producto = SimpleNamespace(
        idProducto=50,
        empresaID=3,
        nombreProducto="Ramo Primavera",
        imageUrl="https://cdn.example.com/ramo.jpg",
    )
    db = FakeDb(entrega=entrega, pedido=pedido, cliente=cliente, detalles=[(detalle, producto)])
    auth = SimpleNamespace(empresaID=3, esGlobalJoin=False, rol="Domiciliario")

    response = domicilios_router.obtener_detalle_domicilio(10, db=db, auth=auth)

    assert response.idEntrega == 10
    assert response.numeroPedido == "FLR-96412"
    assert response.cliente == "Cliente Demo"
    assert response.customerMessage == "Feliz cumple"
    assert response.items[0].productId == 50
    assert response.items[0].name == "Ramo Primavera"
    assert response.items[0].qty == 2
    assert response.items[0].imageUrl == "https://cdn.example.com/ramo.jpg"


def test_obtener_detalle_domicilio_404_when_entrega_missing():
    db = FakeDb(entrega=None)
    auth = SimpleNamespace(empresaID=3, esGlobalJoin=False, rol="Domiciliario")

    with pytest.raises(HTTPException) as exc:
        domicilios_router.obtener_detalle_domicilio(999, db=db, auth=auth)

    assert exc.value.status_code == 404


def test_pedido_disponible_item_uses_codigo_pedido_column():
    entrega = SimpleNamespace(
        direccion="Calle 123",
        estadoEntregaID=1,
        barrioID=None,
        barrioNombre=None,
        reprogramadaPara=None,
        fechaEntregaProgramada=None,
        fechaEntrega=None,
        rangoHora=None,
    )
    pedido = SimpleNamespace(
        idPedido=20,
        numeroPedido=96412,
        codigoPedido="FLR-96412",
    )
    cliente = SimpleNamespace(nombreCompleto="Cliente Demo")
    produccion = SimpleNamespace(prioridad="ALTA")

    item = domicilios_router._build_pedido_disponible_item(entrega, pedido, cliente, produccion)

    assert item.codigoPedido == "FLR-96412"
    assert item.numeroPedido == "FLR-96412"


def test_pedido_disponible_item_prefers_rango_hora_over_midnight_date():
    entrega = SimpleNamespace(
        direccion="Calle 123",
        estadoEntregaID=1,
        barrioID=None,
        barrioNombre=None,
        reprogramadaPara=None,
        fechaEntregaProgramada=datetime(2026, 7, 16, 0, 0, 0),
        fechaEntrega=None,
        rangoHora="10:00",
    )
    pedido = SimpleNamespace(
        idPedido=20,
        numeroPedido=97118,
        codigoPedido=None,
    )
    cliente = SimpleNamespace(nombreCompleto="Laura Tello")
    produccion = SimpleNamespace(prioridad="MEDIA")

    item = domicilios_router._build_pedido_disponible_item(entrega, pedido, cliente, produccion)

    assert item.horaEntrega == "10:00"


def test_devolver_entrega_returns_assigned_delivery_to_available(monkeypatch):
    entrega = SimpleNamespace(
        idEntrega=10,
        empresaID=3,
        domiciliarioID=48,
        fechaAsignacion=datetime(2026, 7, 16, 9, 0, 0),
        fechaSalida=None,
        estadoEntregaID=2,
        updatedAt=None,
    )
    db = SimpleNamespace(committed=False, commit=lambda: setattr(db, "committed", True))
    auth = SimpleNamespace(empresaID=3, esGlobalJoin=False, rol="Domiciliario", userID=100)

    monkeypatch.setattr(domicilios_router, "_locked_current_entrega", lambda *_args, **_kwargs: entrega)
    monkeypatch.setattr(domicilios_router, "_assert_entrega_actor_scope", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(domicilios_router, "assert_same_empresa", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(domicilios_router.domicilio_service, "estado_norm", lambda *_args, **_kwargs: domicilios_router.ESTADO_ASIGNADO)
    monkeypatch.setattr(domicilios_router.domicilio_service, "resolve_estado_entrega_id", lambda *_args, **_kwargs: 1)

    response = domicilios_router.devolver_entrega(
        10,
        domicilios_router.TomarEntregaRequest(usuarioCambio="domiciliario"),
        db=db,
        auth=auth,
    )

    assert response.estado == domicilios_router.ESTADO_PENDIENTE
    assert entrega.domiciliarioID is None
    assert entrega.fechaAsignacion is None
    assert entrega.fechaSalida is None
    assert entrega.estadoEntregaID == 1
    assert db.committed is True


def test_devolver_entrega_rejects_en_ruta(monkeypatch):
    entrega = SimpleNamespace(idEntrega=10, empresaID=3, domiciliarioID=48, estadoEntregaID=3)
    db = SimpleNamespace(commit=lambda: None)
    auth = SimpleNamespace(empresaID=3, esGlobalJoin=False, rol="Domiciliario", userID=100)

    monkeypatch.setattr(domicilios_router, "_locked_current_entrega", lambda *_args, **_kwargs: entrega)
    monkeypatch.setattr(domicilios_router, "_assert_entrega_actor_scope", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(domicilios_router, "assert_same_empresa", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(domicilios_router.domicilio_service, "estado_norm", lambda *_args, **_kwargs: domicilios_router.ESTADO_EN_RUTA)

    with pytest.raises(HTTPException) as exc:
        domicilios_router.devolver_entrega(
            10,
            domicilios_router.TomarEntregaRequest(usuarioCambio="domiciliario"),
            db=db,
            auth=auth,
        )

    assert exc.value.status_code == 400
