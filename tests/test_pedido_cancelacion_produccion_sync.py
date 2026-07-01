from types import SimpleNamespace

from app.models.entrega import Entrega
from app.models.produccion import Produccion
from app.routers import pedido as pedido_router
from app.services import produccion_service


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows
        self.join_args = None
        self.filter_args = None

    def join(self, *args):
        self.join_args = args
        return self

    def filter(self, *args):
        self.filter_args = args
        return self

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, rows_by_model):
        self.rows_by_model = rows_by_model
        self.queries = {}
        self.flush_count = 0
        self.execute_calls = []

    def flush(self):
        self.flush_count += 1

    def execute(self, statement, params=None):
        self.execute_calls.append((statement, params or {}))
        return SimpleNamespace(fetchall=lambda: [(10,)])

    def query(self, model):
        query = FakeQuery(self.rows_by_model.get(model, []))
        self.queries[model] = query
        return query


def test_cancelar_producciones_por_pedido_cancelado_uses_exact_update_rule(monkeypatch):
    row = SimpleNamespace(
        idProduccion=10,
        empresaID=3,
        sucursalID=3,
        pedidoID=20,
        floristaID=7,
        estado=1,
        updatedAt=None,
        observacionesInternas=None,
    )
    db = FakeSession({Produccion: [row]})

    monkeypatch.setattr(produccion_service, "colombia_now_naive", lambda: "now")
    monkeypatch.setattr(produccion_service, "log_historial", lambda **kwargs: None)

    updated = produccion_service.cancelar_producciones_por_pedido_cancelado(
        db,
        pedido_id=20,
        empresa_id=3,
    )

    query = db.queries[Produccion]
    statement, params = db.execute_calls[0]
    sql = str(statement)

    assert updated == 1
    assert db.flush_count == 1
    assert params == {"pedido_id": 20, "empresa_id": 3}
    assert "WITH target AS" in sql
    assert "p.estado_pedido_id = 6" in sql
    assert "pr.estado_produccion_id <> 5" in sql
    assert "UPDATE petalops.produccion" in sql
    assert query.filter_args is not None


def test_sincronizar_cancelacion_operativa_delegates_produccion_to_service(monkeypatch):
    pedido = SimpleNamespace(idPedido=20, empresaID=3)
    entrega = SimpleNamespace(
        pedidoID=20,
        empresaID=3,
        estadoEntregaID=1,
        observaciones=None,
        updatedAt=None,
    )
    db = FakeSession({Entrega: [entrega]})
    captured = {}

    def fake_cancelar(db_arg, *, pedido_id, empresa_id, usuario, motivo):
        captured.update(
            {
                "db": db_arg,
                "pedido_id": pedido_id,
                "empresa_id": empresa_id,
                "usuario": usuario,
                "motivo": motivo,
            }
        )
        return 2

    monkeypatch.setattr(
        pedido_router.produccion_service,
        "cancelar_producciones_por_pedido_cancelado",
        fake_cancelar,
    )
    monkeypatch.setattr(
        pedido_router.domicilio_service,
        "resolve_estado_entrega_id",
        lambda db_arg, estado: 6,
    )

    result = pedido_router._sincronizar_cancelacion_operativa_desde_pedido(
        db,
        pedido,
        motivo="Cliente cancela",
    )

    assert captured["db"] is db
    assert captured["pedido_id"] == 20
    assert captured["empresa_id"] == 3
    assert captured["usuario"] == "pedido.cancelacion_operativa"
    assert "Cliente cancela" in captured["motivo"]
    assert result == {"produccionesCanceladas": 2, "entregasCanceladas": 1}
    assert entrega.estadoEntregaID == 6
