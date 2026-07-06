from datetime import datetime
from zoneinfo import ZoneInfo

from app.routers import pipeline


def test_minutes_left_accepts_timezone_aware_datetime():
    target = datetime(2026, 7, 6, 16, 30, tzinfo=ZoneInfo("America/Bogota"))

    minutes = pipeline._minutes_left(target)

    assert isinstance(minutes, int)
