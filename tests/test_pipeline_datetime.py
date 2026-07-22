from datetime import datetime
from zoneinfo import ZoneInfo

from app.routers import pipeline


def test_minutes_left_accepts_timezone_aware_datetime():
    target = datetime(2026, 7, 6, 16, 30, tzinfo=ZoneInfo("America/Bogota"))

    minutes = pipeline._minutes_left(target)

    assert isinstance(minutes, int)


def test_rango_hora_deadline_uses_end_of_named_window():
    assert pipeline._parse_rango_hora_deadline_time("Manana (8am - 12pm)").hour == 12


def test_rango_hora_deadline_accepts_text_separator():
    deadline = pipeline._parse_rango_hora_deadline_time("Manana (8am a 12pm)")

    assert deadline.hour == 12
    assert deadline.minute == 0


def test_late_deadline_for_midnight_date_uses_delivery_window_end():
    deadline = pipeline._late_deadline(datetime(2026, 7, 22, 0, 0, 0), "Manana (8am - 12pm)")

    assert deadline == datetime(2026, 7, 22, 12, 0, 0)

