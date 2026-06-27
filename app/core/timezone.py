from datetime import date, datetime
from zoneinfo import ZoneInfo


COLOMBIA_TZ = ZoneInfo("America/Bogota")


def colombia_now() -> datetime:
    return datetime.now(COLOMBIA_TZ)


def colombia_now_naive() -> datetime:
    return colombia_now().replace(tzinfo=None)


def colombia_today() -> date:
    return colombia_now().date()


def as_colombia_date(value: date | datetime | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(COLOMBIA_TZ).date()
        return value.date()
    return value


def as_colombia_naive_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(COLOMBIA_TZ).replace(tzinfo=None)
    return value
