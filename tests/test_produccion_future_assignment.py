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

    def first(self):
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
    db = FakeSession([produccion, florista])
    payload = ProduccionAsignarRequest(
        floristaID=7,
        fechaProgramadaProduccion=future_date,
        motivo="Reasignacion futura",
        usuarioCambio="florista1",
    )
    auth = SimpleNamespace(empresaID=3)

    monkeypatch.setattr(produccion_router, "assert_same_empresa", lambda auth_ctx, empresa_id: None)
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
