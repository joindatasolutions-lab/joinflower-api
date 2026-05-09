from datetime import date
from types import SimpleNamespace

from app.routers import produccion as produccion_router
from app.schemas.produccion import ProduccionReasignarRequest


def test_reasignar_produccion_no_longer_blocks_non_admin_florista(monkeypatch):
    payload = ProduccionReasignarRequest(
        floristaNuevoID=7,
        fechaProgramadaProduccion=date(2026, 5, 10),
        motivo="Cambio manual",
        usuarioCambio="florista1",
    )
    auth = SimpleNamespace(
        login="florista1",
        nombre="Elibeth Salgado",
        empresaID=3,
        sucursalID=3,
        rol="Florista",
        userID=12,
    )
    db = object()
    captured = {}

    def fake_asignar(produccion_id, wrapper, db_arg, auth_arg):
        captured["produccion_id"] = produccion_id
        captured["wrapper"] = wrapper
        captured["db"] = db_arg
        captured["auth"] = auth_arg
        return {"status": "ok"}

    monkeypatch.setattr(produccion_router, "asignar_produccion", fake_asignar)

    response = produccion_router.reasignar_produccion(92, payload, db, auth)

    assert response == {"status": "ok"}
    assert captured["produccion_id"] == 92
    assert captured["db"] is db
    assert captured["auth"] is auth
    assert captured["wrapper"].floristaID == 7
    assert captured["wrapper"].fechaProgramadaProduccion == date(2026, 5, 10)
    assert captured["wrapper"].motivo == "Cambio manual"
    assert captured["wrapper"].usuarioCambio == "florista1"
