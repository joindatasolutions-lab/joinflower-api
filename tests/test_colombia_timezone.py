from datetime import datetime, timedelta, timezone

from sqlalchemy import Column, Integer, MetaData, Table, create_engine, select

from app.core.db_types import ColombiaDateTime
from app.core.ordering import _to_utc
from app.core.timezone import COLOMBIA_TZ, as_colombia_naive_datetime
from app.routers.pedido import _parse_iso_date
from app.services.whatsapp_service import _datetime_from_meta_timestamp


def test_utc_input_crosses_midnight_in_colombia():
    assert _parse_iso_date("2026-09-26T02:30:00+00:00") == datetime(2026, 9, 25, 21, 30)


def test_local_datetime_is_not_shifted_twice():
    local = datetime(2026, 9, 25, 21, 30)
    assert as_colombia_naive_datetime(local) == local
    assert as_colombia_naive_datetime(local.replace(tzinfo=COLOMBIA_TZ)) == local
    assert as_colombia_naive_datetime(None) is None


def test_datetime_storage_and_filters_normalize_aware_values():
    engine = create_engine("sqlite://")
    metadata = MetaData()
    table = Table("events", metadata, Column("id", Integer, primary_key=True),
                  Column("at", ColombiaDateTime))
    metadata.create_all(engine)
    utc = datetime(2026, 9, 26, 2, 30, tzinfo=timezone.utc)
    local = datetime(2026, 9, 25, 21, 30)
    with engine.begin() as conn:
        conn.execute(table.insert(), [{"id": 1, "at": utc}, {"id": 2, "at": local},
                                      {"id": 3, "at": None}])
        assert conn.execute(select(table.c.at).order_by(table.c.id)).scalars().all() == [local, local, None]
        assert conn.execute(select(table.c.id).where(table.c.at == utc)).scalars().all() == [1, 2]
    engine.dispose()


def test_ordering_interprets_naive_deadlines_as_colombia():
    local = datetime(2026, 9, 25, 21, 30)
    assert _to_utc(local) == datetime(2026, 9, 26, 2, 30, tzinfo=timezone.utc)


def test_whatsapp_epoch_uses_colombia_wall_time():
    utc = datetime(2026, 9, 26, 2, 30, tzinfo=timezone.utc)
    assert _datetime_from_meta_timestamp(str(int(utc.timestamp()))) == datetime(2026, 9, 25, 21, 30)


def test_other_offsets_preserve_instant():
    value = datetime(2026, 9, 26, 10, tzinfo=timezone(timedelta(hours=2)))
    assert as_colombia_naive_datetime(value) == datetime(2026, 9, 26, 3)
