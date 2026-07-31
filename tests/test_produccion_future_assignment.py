from datetime import date, datetime
from types import SimpleNamespace

from app.routers import produccion as produccion_router
from app.schemas.produccion import ProduccionAsignarRequest


class FakeQuery:
    def __init__(self, result):
        self.result = result

    def filter(self, *_args, **_kwargs):
        return self

    def join(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.result

    def all(self):
        return self.result


class FakeSession:
    def __init__(self, query_results):
        self._query_results = list(query_results)
        self.committed = False

    def query(self, *_args, **_kwargs):
        if not self._query_results:
            raise AssertionError("Unexpected query() call")
        return FakeQuery(self._query_results.pop(0))

    def commit(self):
        self.committed = True


def test_asignar_produccion_allows_future_programmed_date(monkeypatch):
    future_date = date(2026, 5, 10)
    now_utc = datetime(2026, 5, 8, 12, 0, 0)
    produccion = SimpleNamespace(
        idProduccion=99,
        empresaID=3,
        sucursalID=3,
        pedidoID=500,
        floristaID=None,
        fechaProgramadaProduccion=future_date,
        estado=1,
        prioridad="MEDIA",
        observacionesInternas=None,
        fechaAsignacion=None,
        updatedAt=None,
    )
    florista = SimpleNamespace(
        idFlorista=7,
        empresaID=3,
        sucursalID=3,
        nombre="Elibeth Salgado",
    )
    db = FakeSession([produccion, [produccion], florista])
    payload = ProduccionAsignarRequest(
        floristaID=7,
        fechaProgramadaProduccion=future_date,
        motivo="Reasignacion futura",
        usuarioCambio="florista1",
    )
    auth = SimpleNamespace(empresaID=3)

    monkeypatch.setattr(produccion_router, "assert_same_empresa", lambda auth_ctx, empresa_id: None)
    monkeypatch.setattr(produccion_router, "_bloquear_operacion_si_pedido_cancelado", lambda *args, **kwargs: None)
    monkeypatch.setattr(produccion_router.produccion_service, "_resolve_estado_produccion_ids", lambda db: {"cancelado": 5})
    monkeypatch.setattr(produccion_router, "_estado_produccion_norm", lambda value, db=None: produccion_router.ESTADO_PENDIENTE)
    monkeypatch.setattr(produccion_router, "_validate_florista_disponibilidad", lambda **kwargs: None)
    monkeypatch.setattr(produccion_router, "_utc_now_naive", lambda: now_utc)
    monkeypatch.setattr(produccion_router, "_log_historial", lambda *args, **kwargs: None)

    response = produccion_router.asignar_produccion(99, payload, db, auth)

    assert response["status"] == "ok"
    assert response["idProduccion"] == 99
    assert response["floristaID"] == 7
    assert response["fechaProgramadaProduccion"] == "2026-05-10"
    assert produccion.floristaID == 7
    assert produccion.fechaProgramadaProduccion == future_date
    assert produccion.fechaAsignacion == now_utc
    assert produccion.updatedAt == now_utc
    assert db.committed is True


def test_asignar_produccion_updates_every_row_for_same_order(monkeypatch):
    future_date = date(2026, 5, 10)
    now_utc = datetime(2026, 5, 8, 12, 0, 0)
    produccion_a = SimpleNamespace(
        idProduccion=99,
        empresaID=3,
        sucursalID=3,
        pedidoID=500,
        floristaID=4,
        fechaProgramadaProduccion=future_date,
        estado=1,
        prioridad="MEDIA",
        observacionesInternas=None,
        fechaAsignacion=None,
        updatedAt=None,
    )
    produccion_b = SimpleNamespace(
        idProduccion=100,
        empresaID=3,
        sucursalID=3,
        pedidoID=500,
        floristaID=9,
        fechaProgramadaProduccion=future_date,
        estado=1,
        prioridad="MEDIA",
        observacionesInternas=None,
        fechaAsignacion=None,
        updatedAt=None,
    )
    florista = SimpleNamespace(
        idFlorista=7,
        empresaID=3,
        sucursalID=3,
        nombre="Elibeth Salgado",
    )
    db = FakeSession([produccion_a, [produccion_a, produccion_b], florista])
    payload = ProduccionAsignarRequest(
        floristaID=7,
        fechaProgramadaProduccion=future_date,
        motivo="Reasignacion total",
        usuarioCambio="coordinador",
    )
    auth = SimpleNamespace(empresaID=3)
    historial = []

    monkeypatch.setattr(produccion_router, "assert_same_empresa", lambda auth_ctx, empresa_id: None)
    monkeypatch.setattr(produccion_router, "_bloquear_operacion_si_pedido_cancelado", lambda *args, **kwargs: None)
    monkeypatch.setattr(produccion_router.produccion_service, "_resolve_estado_produccion_ids", lambda db: {"cancelado": 5})
    monkeypatch.setattr(produccion_router, "_estado_produccion_norm", lambda value, db=None: produccion_router.ESTADO_PENDIENTE)
    monkeypatch.setattr(produccion_router, "_validate_florista_disponibilidad", lambda **kwargs: None)
    monkeypatch.setattr(produccion_router, "_utc_now_naive", lambda: now_utc)
    monkeypatch.setattr(produccion_router, "_log_historial", lambda *args, **kwargs: historial.append(kwargs))

    response = produccion_router.asignar_produccion(99, payload, db, auth)

    assert response["status"] == "ok"
    assert response["pedidoID"] == 500
    assert response["produccionesActualizadas"] == 2
    assert produccion_a.floristaID == 7
    assert produccion_b.floristaID == 7
    assert produccion_a.fechaAsignacion == now_utc
    assert produccion_b.fechaAsignacion == now_utc
    assert [item["produccion"].idProduccion for item in historial] == [99, 100]
    assert db.committed is True
