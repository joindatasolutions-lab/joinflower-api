from app.routers.produccion import _is_manual_historial_event, _tipo_movimiento_historial


def test_manual_historial_event_excludes_automatic_reasons():
    assert _is_manual_historial_event("Asignación automática por aprobación del pedido", "pedido.aprobar") is False
    assert _is_manual_historial_event("Reasignación automática por incapacidad activa", "system") is False


def test_manual_historial_event_keeps_manual_actions():
    assert _is_manual_historial_event("Reasignación desde panel de producción", "flora.admin") is True
    assert _is_manual_historial_event("Cambio manual", "florista1") is True


def test_tipo_movimiento_historial_labels_manual_events():
    assert _tipo_movimiento_historial(None, 7) == "ASIGNACION_MANUAL"
    assert _tipo_movimiento_historial(7, 8) == "REASIGNACION_MANUAL"
    assert _tipo_movimiento_historial(7, None) == "DESASIGNACION_MANUAL"
