from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.models.entrega import Entrega
from app.routers import domicilios as router
from app.services import domicilio_service as service


@pytest.fixture
def context(monkeypatch):
    entrega = Entrega(idEntrega=10, empresaID=3, pedidoID=20, sucursalID=1,
                      domiciliarioID=48, estadoEntregaID=5, intentoNumero=2,
                      barrioNombre="Centro", motivoNoEntregado="No responde",
                      reprogramadaPara=datetime(2026, 11, 10, 12))
    db = Mock()
    db.add.side_effect = lambda row: setattr(row, "idEntrega", 11)
    auth = SimpleNamespace(empresaID=3, userID=100, login="admin", rol="Admin", esGlobalJoin=False)
    monkeypatch.setattr(router, "_locked_current_entrega", lambda *_: entrega)
    monkeypatch.setattr(router, "_assert_entrega_actor_scope", Mock())
    monkeypatch.setattr(service, "resolve_estado_entrega_id", lambda db, state: service.ESTADO_ID_FALLBACK[state])
    transition = Mock()
    monkeypatch.setattr(service, "assert_transition_allowed_for_empresa", transition)
    monkeypatch.setattr(service, "assert_domiciliario_capacity", Mock())
    audit = Mock()
    monkeypatch.setattr(router, "_audit_domicilio_action", audit)
    monkeypatch.setattr(router.whatsapp_service, "encolar_notificacion_nuevo_pedido_domiciliario", Mock())
    return entrega, db, auth, transition, audit


def test_new_attempt_keeps_old_snapshot_and_reschedules(context):
    old, db, auth, transition, audit = context
    fecha = datetime(2026, 11, 11, 9)
    response = router._resolver_novedad_operativa(10, "nuevo_intento", "Cliente confirma", fecha, db, auth)
    nuevo = db.add.call_args.args[0]
    assert response.idEntrega == 11
    assert nuevo.intentoNumero == 3
    assert nuevo.domiciliarioID == 48
    assert nuevo.barrioNombre == old.barrioNombre
    assert nuevo.reprogramadaPara == nuevo.fechaEntregaProgramada == fecha
    assert nuevo.motivoNoEntregado is None
    assert old.estadoEntregaID == 5 and old.motivoNoEntregado == "No responde"
    assert audit.call_args.kwargs["entrega"] is old
    assert audit.call_args.kwargs["extra"]["nuevaEntregaID"] == 11
    assert transition.call_args.kwargs["strict"] is True
    db.commit.assert_called_once()


def test_return_releases_courier_without_new_attempt(context):
    entrega, db, auth, transition, audit = context
    result = router._resolver_novedad_operativa(10, "devolver_disponibles", "Reasignar", None, db, auth)
    assert result.idEntrega == 10 and result.estado == "Pendiente"
    assert entrega.domiciliarioID is None
    assert entrega.fechaAsignacion is None and entrega.fechaSalida is None
    assert entrega.intentoNumero == 2
    assert audit.call_args.kwargs["extra"]["domiciliarioAnteriorID"] == 48
    db.add.assert_not_called()


@pytest.mark.parametrize("state", [1, 2, 3, 4, 6])
def test_only_failed_delivery_can_be_resolved(context, state):
    entrega, db, auth, transition, audit = context
    entrega.estadoEntregaID = state
    with pytest.raises(HTTPException) as exc:
        router._resolver_novedad_operativa(10, "nuevo_intento", "Reintentar", None, db, auth)
    assert exc.value.status_code == 400
    db.commit.assert_not_called()
    audit.assert_not_called()


def test_rejected_transition_does_not_mutate(context):
    entrega, db, auth, transition, audit = context
    transition.side_effect = HTTPException(400, "Transicion no permitida")
    with pytest.raises(HTTPException):
        router._resolver_novedad_operativa(10, "devolver_disponibles", "Reasignar", None, db, auth)
    assert entrega.estadoEntregaID == 5 and entrega.domiciliarioID == 48
    db.commit.assert_not_called()


def test_strict_transition_does_not_seed_missing_permission(monkeypatch):
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = None
    monkeypatch.setattr(service, "resolve_estado_entrega_id", lambda db, state: service.ESTADO_ID_FALLBACK[state])
    monkeypatch.setattr(service, "_transicion_estado_entrega_table_exists", lambda db: True)
    seed = Mock()
    monkeypatch.setattr(service, "_ensure_transiciones_entrega_defaults", seed)
    with pytest.raises(HTTPException):
        service.assert_transition_allowed_for_empresa(db, 3, "NoEntregado", "Entregado", strict=True)
    seed.assert_not_called()


@pytest.mark.parametrize("assigned", [None, 49])
def test_courier_cannot_resolve_other_delivery(monkeypatch, assigned):
    monkeypatch.setattr(router, "_actor_can_override_delivery", lambda auth: False)
    monkeypatch.setattr(router, "_domiciliario_id_for_auth", lambda db, auth: assigned)
    with pytest.raises(HTTPException) as exc:
        router._assert_entrega_actor_scope(SimpleNamespace(domiciliarioID=48), SimpleNamespace(rol="Domiciliario"), Mock())
    assert exc.value.status_code == 403


def test_equal_timestamp_resolution_and_unrelated_change():
    fecha = datetime(2026, 11, 10, 9)
    events = [router.DomicilioAuditItem(accion="NO_ENTREGADO", createdAt=fecha, detalle={"motivo": "Ausente"}),
              router.DomicilioAuditItem(accion="CORRECCION", estadoNuevo="Pendiente", createdAt=fecha)]
    assert router._novedad_audit_summary(events, SimpleNamespace())["resueltaEn"] is None
    events.append(router.DomicilioAuditItem(accion="RESOLVER_NOVEDAD", createdAt=fecha, actorLogin="admin"))
    assert router._novedad_audit_summary(events, SimpleNamespace())["resueltaPor"] == "admin"


def test_endpoint_requires_edit_permission():
    app = FastAPI()
    app.include_router(router.router)
    auth = SimpleNamespace(empresaID=3, rol="Domiciliario", esGlobalJoin=False,
                           modulosActivosPlan={"domicilios"}, can=lambda module, action: action == "puedeVer")
    app.dependency_overrides[router.get_current_auth_context] = lambda: auth
    app.dependency_overrides[router.get_db] = lambda: Mock()
    response = TestClient(app).put("/domicilios/10/resolver-novedad", data={
        "usuarioCambio": "otro", "accion": "devolver_disponibles", "observaciones": "Reasignar"})
    assert response.status_code == 403


@pytest.mark.parametrize("accion,observaciones,expected", [
    ("devolver_disponibles", "Reasignar", 200),
    ("nuevo_intento", "Reintentar", 200),
    ("otra", "Reasignar", 422),
    ("entregar", "   ", 422),
])
def test_form_contract(context, accion, observaciones, expected):
    entrega, db, auth, transition, audit = context
    auth.modulosActivosPlan = {"domicilios"}
    auth.can = lambda *_: True
    app = FastAPI()
    app.include_router(router.router)
    app.dependency_overrides[router.get_current_auth_context] = lambda: auth
    app.dependency_overrides[router.get_db] = lambda: db
    result = TestClient(app).put("/domicilios/10/resolver-novedad", data={
        "usuarioCambio": "nombre no confiable", "accion": accion, "observaciones": observaciones,
    })
    assert result.status_code == expected
    if expected == 200:
        assert result.json()["status"] == "ok"
        assert audit.call_args.kwargs["auth"].login == "admin"
    else:
        db.commit.assert_not_called()


def test_history_counts_and_courier_scope(monkeypatch):
    monkeypatch.setattr(router, "_ensure_domicilio_auditoria_table", lambda db: None)
    monkeypatch.setattr(router, "_actor_can_override_delivery", lambda auth: False)
    monkeypatch.setattr(router, "_domiciliario_id_for_auth", lambda db, auth: 48)
    db = Mock()
    db.execute.return_value.mappings.return_value.one.return_value = {"abiertas": 2, "resueltas": 5}
    db.execute.return_value.mappings.return_value.all.return_value = [{
        "id_audit": 20, "pedido_id": 7, "entrega_id": 9, "domiciliario_id": 48,
        "estado": "resuelta", "detalle_json": '{"motivo":"Ausente"}',
        "resolucion_json": '{"accionResolucion":"nuevo_intento","nuevaEntregaID":10,"observaciones":"Confirmado"}',
        "resolucion_accion": "RESOLVER_NOVEDAD", "actor_login": "domi",
        "created_at": datetime(2026, 11, 10, 9), "resuelta_por": "admin", "resuelta_en": datetime(2026, 11, 10, 10),
    }]
    result = router.listar_novedades(estado="resuelta", limite=50, offset=0, db=db,
                                   auth=SimpleNamespace(empresaID=3, rol="Domiciliario"))
    assert (result.abiertas, result.resueltas, result.total) == (2, 5, 5)
    assert result.items[0].nuevaEntregaID == 10
    assert result.items[0].observacionResolucion == "Confirmado"
    for call in db.execute.call_args_list:
        assert call.args[1]["empresa"] == 3 and call.args[1]["domiciliario"] == 48
