from datetime import datetime, timezone

from app.routers.pedido import _fecha_filtro_pedido, _fecha_pedido_str, _fecha_respuesta_pedido, _hora_pedido_str


def test_fecha_filtro_pedido_converts_utc_range_to_colombia_naive_datetime():
    utc_end_of_colombia_day = datetime(2026, 7, 16, 4, 59, 59, tzinfo=timezone.utc)

    normalized = _fecha_filtro_pedido(utc_end_of_colombia_day)

    assert normalized == datetime(2026, 7, 15, 23, 59, 59)


def test_fecha_respuesta_pedido_is_returned_in_colombia_time():
    utc_value = datetime(2026, 7, 16, 5, 9, 19, tzinfo=timezone.utc)

    normalized = _fecha_respuesta_pedido(utc_value)

    assert normalized == datetime(2026, 7, 16, 0, 9, 19)
    assert _fecha_pedido_str(utc_value) == "2026-07-16"
    assert _hora_pedido_str(utc_value) == "00:09:19"
