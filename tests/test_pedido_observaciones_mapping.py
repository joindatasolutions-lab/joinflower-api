from datetime import date
from types import SimpleNamespace

from app.models.entrega import Entrega
from app.models.pedidodetalle import PedidoDetalle
from app.models.produccion import Produccion
from app.routers import pedido as pedido_router
from app.services import produccion_service


class QueueQuery:
    def __init__(self, rows=None, first_row=None, scalar_value=None):
        self.rows = rows or []
        self.first_row = first_row
        self.scalar_value = scalar_value

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.first_row

    def scalar(self):
        return self.scalar_value


class QueueSession:
    def __init__(self, queries):
        self.queries = list(queries)
        self.added = []
        self.flush_count = 0

    def query(self, *_args, **_kwargs):
        if not self.queries:
            raise AssertionError("Unexpected query")
        return self.queries.pop(0)

    def add(self, item):
        if isinstance(item, Produccion) and item.idProduccion is None:
            item.idProduccion = len(self.added) + 1
        self.added.append(item)

    def flush(self):
        self.flush_count += 1


def test_aprobar_pedido_copia_notas_produccion_a_observaciones_internas(monkeypatch):
    pedido = SimpleNamespace(idPedido=20, empresaID=3, sucursalID=3)
    entrega = SimpleNamespace(fechaEntregaProgramada=None, fechaEntrega=None, reprogramadaPara=None)
    detalle = SimpleNamespace(
        idPedidoDetalle=30,
        observacionesPersonalizados="PRUEBA JOIN DATA",
        cantidad=1,
    )
    db = QueueSession(
        [
            QueueQuery(first_row=entrega),
            QueueQuery(rows=[detalle]),
            QueueQuery(rows=[]),
            QueueQuery(scalar_value=0),
        ]
    )

    monkeypatch.setattr(produccion_service, "_resolve_estado_produccion_ids", lambda _db: {"pendiente": 1, "cancelado": 5})
    monkeypatch.setattr(produccion_service, "calcular_fecha_programada", lambda **_kwargs: date(2099, 1, 1))
    monkeypatch.setattr(produccion_service, "calcular_tiempo_estimado_detalle", lambda _detalle: 30)
    monkeypatch.setattr(produccion_service, "validar_unico_florista_por_pedido", lambda _producciones: None)

    result = produccion_service.asegurar_produccion_desde_pedido_aprobado_por_detalle(
        db=db,
        pedido=pedido,
        dias_anticipacion=0,
    )

    assert result["createdCount"] == 1
    assert db.added[0].observacionesInternas == "PRUEBA JOIN DATA"


def test_edicion_sincroniza_notas_produccion_en_produccion_existente(monkeypatch):
    produccion = SimpleNamespace(
        pedidoID=20,
        empresaID=3,
        pedidoDetalleID=30,
        estado=1,
        observacionesInternas=None,
        updatedAt=None,
    )
    db = QueueSession([QueueQuery(rows=[produccion])])

    monkeypatch.setattr(pedido_router.produccion_service, "estado_produccion_id", lambda *_args, **_kwargs: 5)
    monkeypatch.setattr(pedido_router, "colombia_now_naive", lambda: "now")

    pedido_router._sync_produccion_observaciones_internas_desde_detalle(
        db,
        pedido_id=20,
        empresa_id=3,
        detalle_id=30,
        notas_produccion="Nueva nota",
    )

    assert produccion.observacionesInternas == "Nueva nota"
    assert produccion.updatedAt == "now"
