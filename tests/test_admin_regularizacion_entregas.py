from datetime import date, datetime, time

import pytest
from fastapi import HTTPException

from app.routers import admin as admin_router
from app.schemas.admin import RegularizarEntregasRequest


def test_regularizacion_payload_supports_bulk_items():
    payload = RegularizarEntregasRequest(
        fecha_entrega=date(2026, 8, 17),
        domiciliario_id=123,
        motivo="Pedido entregado fisicamente pero no asignado en el sistema",
        pedidos=[
            {"pedido_id": 98047, "hora_entrega": "10:15"},
            {"pedido_id": 98051, "hora_entrega": "10:30"},
        ],
    )

    items = admin_router._regularizacion_items(payload)

    assert [item.pedido_id for item in items] == [98047, 98051]
    assert items[0].hora_entrega == time(10, 15)


def test_regularizacion_payload_supports_single_item():
    payload = RegularizarEntregasRequest(
        fecha_entrega=date(2026, 8, 17),
        domiciliario_id=123,
        motivo_regularizacion="Regularizacion administrativa con soporte operativo",
        pedido_id=98047,
        hora_entrega=time(10, 15),
    )

    items = admin_router._regularizacion_items(payload)

    assert len(items) == 1
    assert items[0].pedido_id == 98047


def test_timeline_regularizacion_is_chronological():
    programada = datetime(2026, 8, 17, 9, 0)
    entregada = datetime(2026, 8, 17, 10, 15)

    asignacion, salida = admin_router._timeline_for_regularizacion(programada, entregada)

    assert programada <= asignacion <= salida <= entregada
    assert asignacion == datetime(2026, 8, 17, 9, 40)
    assert salida == datetime(2026, 8, 17, 10, 0)


def test_timeline_regularizacion_rejects_delivery_before_schedule():
    with pytest.raises(HTTPException) as exc:
        admin_router._timeline_for_regularizacion(
            datetime(2026, 8, 17, 9, 0),
            datetime(2026, 8, 17, 8, 59),
        )

    assert exc.value.status_code == 400
