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


class FakeMetricasResult:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class FakeMetricasDb:
    def __init__(self, rows):
        self.rows = rows
        self.last_params = None

    def execute(self, query, params):
        self.last_query = str(query)
        self.last_params = params
        return FakeMetricasResult(self.rows)


def test_obtener_detalle_domicilio_returns_items_with_images(monkeypatch):
    monkeypatch.setattr(domicilios_router, "_assert_entrega_actor_scope", lambda *args, **kwargs: None)
    monkeypatch.setattr(domicilios_router, "_domicilio_auditoria", lambda *args, **kwargs: [])

    entrega = SimpleNamespace(
        idEntrega=10,
        empresaID=3,
        pedidoID=20,
        mensaje="Feliz cumple",
        domiciliarioID=48,
        estadoEntregaID=4,
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
    assert response.numeroPedido == "96412"
    assert response.cliente == "Cliente Demo"
    assert response.estado == domicilios_router.ESTADO_ENTREGADO
    assert response.customerMessage == "Feliz cumple"
    assert response.auditoria == []
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


def test_pedido_disponible_item_can_include_product_names():
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
        numeroPedido=97143,
        codigoPedido="FLR-97143",
    )
    cliente = SimpleNamespace(nombreCompleto="Rashidd bojanini Yance")
    produccion = SimpleNamespace(prioridad="ALTA")

    item = domicilios_router._build_pedido_disponible_item(
        entrega,
        pedido,
        cliente,
        produccion,
        arreglo="Ramo Primavera, 2 x Caja de Rosas",
        productos=["Ramo Primavera", "2 x Caja de Rosas"],
        image_url="https://cdn.example.com/ramo.jpg",
    )

    assert item.numeroPedido == "FLR-97143"
    assert item.arreglo == "Ramo Primavera, 2 x Caja de Rosas"
    assert item.nombreArreglo == "Ramo Primavera, 2 x Caja de Rosas"
    assert item.producto == "Ramo Primavera, 2 x Caja de Rosas"
    assert item.productos == ["Ramo Primavera", "2 x Caja de Rosas"]
    assert item.imageUrl == "https://cdn.example.com/ramo.jpg"


def test_product_label_prefers_catalog_code_for_flora_empresa():
    label = domicilios_router._product_label(
        "Bouquet 12 Rosas Rojas",
        Decimal("1"),
        codigo_producto="PROD-0052",
        codigo_catalogo="0052",
        empresa_id=3,
    )

    assert label == "0052 - Bouquet 12 Rosas Rojas"


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


def test_metricas_novedades_detalle_returns_order_detail():
    fecha_programada = datetime(2026, 7, 16, 10, 0, 0)
    db = FakeMetricasDb(
        [
            {
                "id_entrega": 10,
                "pedido_id": 20,
                "numero_pedido": 96412,
                "codigo_pedido": "FLR-96412",
                "cliente": "Cliente Demo",
                "destinatario": "Maria Demo",
                "telefonodestino": "3001234567",
                "direccion": "Calle 123",
                "barrio_id": 7,
                "barrio": "El Prado",
                "zona_id": 2,
                "zona": "Zona 2",
                "domiciliario_id": 48,
                "domiciliario": "Domi Demo",
                "estado_entrega": "No entregado",
                "estado_pedido": "En despacho",
                "novedad": "Dirección incorrecta",
                "intentonumero": 1,
                "fechaentregaprogramada": fecha_programada,
                "fechaentrega": None,
                "reprogramadapara": None,
            }
        ]
    )
    params = {
        "empresa_id": 3,
        "sucursal_id": None,
        "fecha_desde": datetime(2026, 7, 1),
        "fecha_hasta": datetime(2026, 8, 1),
        "domiciliario_id": None,
    }

    detalles = domicilios_router._metricas_novedades_detalle(db, params)

    assert db.last_params == params
    assert "motivonoentregado" in db.last_query
    assert detalles[0].idEntrega == 10
    assert detalles[0].pedidoID == 20
    assert detalles[0].numeroPedido == "96412"
    assert detalles[0].cliente == "Cliente Demo"
    assert detalles[0].domiciliario == "Domi Demo"
    assert detalles[0].novedad == "Dirección incorrecta"
    assert detalles[0].fechaEntregaProgramada == fecha_programada


def test_novedad_audit_summary_tracks_resolution():
    novedad_at = datetime(2026, 7, 23, 9, 30, 0)
    resolved_at = datetime(2026, 7, 23, 11, 45, 0)
    entrega = SimpleNamespace(motivoNoEntregado="Dirección incorrecta")
    auditoria = [
        domicilios_router.DomicilioAuditItem(
            accion="MARCAR_NO_ENTREGADO",
            estadoAnterior="en_ruta",
            estadoNuevo="no_entregado",
            actorLogin="mateo",
            detalle={"motivo": "Dirección incorrecta"},
            createdAt=novedad_at,
        ),
        domicilios_router.DomicilioAuditItem(
            accion="RESOLVER_NOVEDAD",
            estadoAnterior="no_entregado",
            estadoNuevo="entregado",
            actorLogin="admin",
            detalle={"solucion": "Pedido entregado después de resolver la novedad"},
            createdAt=resolved_at,
        ),
    ]

    summary = domicilios_router._novedad_audit_summary(auditoria, entrega)

    assert summary["novedad"] == "Dirección incorrecta"
    assert summary["novedadRegistradaEn"] == novedad_at
    assert summary["novedadRegistradaPor"] == "mateo"
    assert summary["resolucion"] == "Pedido entregado después de resolver la novedad"
    assert summary["resueltaEn"] == resolved_at
    assert summary["resueltaPor"] == "admin"


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
    monkeypatch.setattr(domicilios_router, "_audit_domicilio_action", lambda *_args, **_kwargs: None)

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
    monkeypatch.setattr(domicilios_router, "_audit_domicilio_action", lambda *_args, **_kwargs: None)

    with pytest.raises(HTTPException) as exc:
        domicilios_router.devolver_entrega(
            10,
            domicilios_router.TomarEntregaRequest(usuarioCambio="domiciliario"),
            db=db,
            auth=auth,
        )

    assert exc.value.status_code == 400


def test_marcar_entregado_resolves_novedad_without_signature(monkeypatch):
    entrega = SimpleNamespace(
        idEntrega=10,
        empresaID=3,
        pedidoID=20,
        sucursalID=1,
        domiciliarioID=48,
        estadoEntregaID=5,
        firmaNombre=None,
        firmaDocumento=None,
        firmaImagenUrl=None,
        evidenciaFotoUrl=None,
        latitudEntrega=None,
        longitudEntrega=None,
        observaciones=None,
        updatedAt=None,
    )
    db = SimpleNamespace(committed=False, commit=lambda: setattr(db, "committed", True))
    auth = SimpleNamespace(empresaID=3, esGlobalJoin=False, rol="Empresa Admin", userID=100, login="admin")

    monkeypatch.setattr(domicilios_router, "_locked_current_entrega", lambda *_args, **_kwargs: entrega)
    monkeypatch.setattr(domicilios_router, "_assert_entrega_actor_scope", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(domicilios_router, "assert_same_empresa", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(domicilios_router.domicilio_service, "estado_norm", lambda *_args, **_kwargs: domicilios_router.ESTADO_NO_ENTREGADO)
    monkeypatch.setattr(domicilios_router.domicilio_service, "assert_transition_allowed_for_empresa", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(domicilios_router.domicilio_service, "resolve_estado_entrega_id", lambda *_args, **_kwargs: 4)
    monkeypatch.setattr(domicilios_router, "_audit_domicilio_action", lambda *_args, **_kwargs: None)

    response = domicilios_router.marcar_entregado(
        10,
        usuarioCambio="admin",
        firmaNombre=None,
        firmaDocumento=None,
        firmaImagenUrl=None,
        evidenciaFotoUrl=None,
        latitudEntrega=None,
        longitudEntrega=None,
        observaciones="Nueva dirección",
        firmaImagen=None,
        evidenciaFoto=None,
        db=db,
        auth=auth,
    )

    assert response.estado == domicilios_router.ESTADO_ENTREGADO
    assert entrega.estadoEntregaID == 4
    assert entrega.firmaNombre is None
    assert entrega.firmaDocumento is None
    assert entrega.latitudEntrega is None
    assert entrega.longitudEntrega is None
    assert entrega.observaciones == "Nueva dirección"
    assert db.committed is True


def test_resolver_novedad_endpoint_marks_delivered(monkeypatch):
    entrega = SimpleNamespace(
        idEntrega=10,
        empresaID=3,
        pedidoID=20,
        sucursalID=1,
        domiciliarioID=48,
        estadoEntregaID=5,
        firmaNombre=None,
        firmaDocumento=None,
        firmaImagenUrl=None,
        evidenciaFotoUrl=None,
        latitudEntrega=None,
        longitudEntrega=None,
        observaciones=None,
        updatedAt=None,
    )
    db = SimpleNamespace(committed=False, commit=lambda: setattr(db, "committed", True))
    auth = SimpleNamespace(empresaID=3, esGlobalJoin=False, rol="Empresa Admin", userID=100, login="admin")
    audit_calls = []

    monkeypatch.setattr(domicilios_router, "_locked_current_entrega", lambda *_args, **_kwargs: entrega)
    monkeypatch.setattr(domicilios_router, "_assert_entrega_actor_scope", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(domicilios_router, "assert_same_empresa", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(domicilios_router.domicilio_service, "estado_norm", lambda *_args, **_kwargs: domicilios_router.ESTADO_NO_ENTREGADO)
    monkeypatch.setattr(domicilios_router.domicilio_service, "assert_transition_allowed_for_empresa", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(domicilios_router.domicilio_service, "resolve_estado_entrega_id", lambda *_args, **_kwargs: 4)
    monkeypatch.setattr(domicilios_router, "_audit_domicilio_action", lambda **kwargs: audit_calls.append(kwargs))

    response = domicilios_router.resolver_novedad(
        10,
        usuarioCambio="admin",
        observaciones="Nueva dirección",
        evidenciaFotoUrl=None,
        latitudEntrega=None,
        longitudEntrega=None,
        firmaNombre=None,
        firmaDocumento=None,
        firmaImagenUrl=None,
        firmaImagen=None,
        evidenciaFoto=None,
        db=db,
        auth=auth,
    )

    assert response.estado == domicilios_router.ESTADO_ENTREGADO
    assert entrega.estadoEntregaID == 4
    assert entrega.observaciones == "Nueva dirección"
    assert audit_calls[0]["accion"] == "RESOLVER_NOVEDAD"
    assert db.committed is True


def test_marcar_entregado_allows_optional_signature(monkeypatch):
    entrega = SimpleNamespace(
        idEntrega=10,
        empresaID=3,
        pedidoID=20,
        sucursalID=1,
        domiciliarioID=48,
        estadoEntregaID=3,
        firmaNombre=None,
        firmaDocumento=None,
        firmaImagenUrl=None,
        evidenciaFotoUrl=None,
        latitudEntrega=None,
        longitudEntrega=None,
        observaciones=None,
        updatedAt=None,
    )
    db = SimpleNamespace(committed=False, commit=lambda: setattr(db, "committed", True))
    auth = SimpleNamespace(empresaID=3, esGlobalJoin=False, rol="Domiciliario", userID=100, login="domi")

    monkeypatch.setattr(domicilios_router, "_locked_current_entrega", lambda *_args, **_kwargs: entrega)
    monkeypatch.setattr(domicilios_router, "_assert_entrega_actor_scope", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(domicilios_router, "assert_same_empresa", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(domicilios_router.domicilio_service, "estado_norm", lambda *_args, **_kwargs: domicilios_router.ESTADO_EN_RUTA)
    monkeypatch.setattr(domicilios_router.domicilio_service, "assert_transition_allowed_for_empresa", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(domicilios_router.domicilio_service, "resolve_estado_entrega_id", lambda *_args, **_kwargs: 4)
    monkeypatch.setattr(domicilios_router, "_audit_domicilio_action", lambda *_args, **_kwargs: None)

    response = domicilios_router.marcar_entregado(
        10,
        usuarioCambio="domi",
        firmaNombre=None,
        firmaDocumento=None,
        firmaImagenUrl=None,
        evidenciaFotoUrl=None,
        latitudEntrega=4.7109,
        longitudEntrega=-74.0721,
        observaciones=None,
        firmaImagen=None,
        evidenciaFoto=None,
        db=db,
        auth=auth,
    )

    assert response.estado == domicilios_router.ESTADO_ENTREGADO
    assert entrega.firmaNombre is None
    assert entrega.firmaDocumento is None
    assert entrega.latitudEntrega == 4.7109
    assert entrega.longitudEntrega == -74.0721
    assert db.committed is True
