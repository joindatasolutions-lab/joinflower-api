from datetime import date, datetime
from types import SimpleNamespace

from app.routers import produccion as produccion_router
from app.schemas.produccion import ProduccionEstadoRequest


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


def test_admin_can_change_estado_without_being_assigned_florista(monkeypatch):
    now = datetime(2026, 5, 8, 12, 0, 0)
    produccion = SimpleNamespace(
        idProduccion=101,
        empresaID=3,
        sucursalID=3,
        pedidoID=501,
        floristaID=7,
        fechaProgramadaProduccion=date(2026, 5, 10),
        estado=1,
        observacionesInternas=None,
        fechaInicio=None,
        fechaFinalizacion=None,
        tiempoRealMin=None,
        updatedAt=None,
    )
    florista = SimpleNamespace(
        idFlorista=7,
        empresaID=3,
        sucursalID=3,
        nombre="Florista Asignado",
        cargo="FLORISTA",
        estado="Activo",
        activo=1,
    )
    db = FakeSession([produccion, florista])
    payload = ProduccionEstadoRequest(
        nuevoEstado=produccion_router.ESTADO_EN_PRODUCCION,
        observacionesInternas="Cambio de estado desde panel administrador",
        usuarioCambio="usuario/admin",
        origenCambio="administrador",
        cambioAdministrativo=True,
    )
    auth = SimpleNamespace(
        login="admin",
        nombre="Admin",
        empresaID=3,
        sucursalID=3,
        rol="Admin",
        userID=12,
        esGlobalJoin=False,
    )
    historial = {}

    monkeypatch.setattr(produccion_router, "assert_same_empresa", lambda auth_ctx, empresa_id: None)
    monkeypatch.setattr(produccion_router, "_current_florista_for_user", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("florista ownership should not be checked")))
    monkeypatch.setattr(produccion_router.domicilio_service, "is_produccion_bloqueada_por_entrega_en_ruta", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(produccion_router.produccion_service, "produccion_tiene_pedido_cancelado", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(produccion_router.produccion_service, "transicion_produccion_permitida", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        produccion_router,
        "_estado_produccion_norm",
        lambda value, db=None: {
            1: produccion_router.ESTADO_PENDIENTE,
            produccion_router.ESTADO_EN_PRODUCCION: produccion_router.ESTADO_EN_PRODUCCION,
        }[value],
    )
    monkeypatch.setattr(produccion_router.produccion_service, "estado_produccion_id", lambda db_arg, estado: 2)
    monkeypatch.setattr(produccion_router, "_validate_florista_disponibilidad", lambda **_kwargs: None)
    monkeypatch.setattr(produccion_router, "_utc_now_naive", lambda: now)
    monkeypatch.setattr(produccion_router, "_log_historial", lambda **kwargs: historial.update(kwargs))

    response = produccion_router.cambiar_estado_produccion(101, payload, db, auth)

    assert response["status"] == "ok"
    assert response["estado"] == produccion_router.ESTADO_EN_PRODUCCION
    assert produccion.estado == 2
    assert produccion.fechaInicio == now
    assert produccion.observacionesInternas == "Cambio de estado desde panel administrador"
    assert db.committed is True
    assert historial["usuario"] == "usuario/admin"
    assert historial["motivo"] == "Cambio administrativo de estado: Pendiente -> EnProduccion"
