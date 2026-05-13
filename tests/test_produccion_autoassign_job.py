from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from app.jobs import produccion_autoassign_job as job_module


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *args, **kwargs):
        return self

    def group_by(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return list(self._rows)


class _FakeDb:
    def __init__(self, scope_rows):
        self.scope_rows = scope_rows
        self.closed = False
        self.commits = 0
        self.rollbacks = 0

    def query(self, *args, **kwargs):
        return _FakeQuery(self.scope_rows)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def test_run_autoassign_today_once_aggregates_empresa_sucursal_stats(monkeypatch):
    fake_db = _FakeDb(scope_rows=[(3, 3), (5, 1)])
    calls = []

    monkeypatch.setattr(job_module, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(job_module, "_acquire_advisory_lock", lambda db: True)
    monkeypatch.setattr(job_module, "_release_advisory_lock", lambda db: None)
    monkeypatch.setattr(
        job_module.produccion_service,
        "_resolve_estado_produccion_ids",
        lambda db: {"pendiente": 1},
    )

    def fake_asignar(**kwargs):
        calls.append(kwargs)
        if int(kwargs["empresa_id"]) == 3:
            return {"evaluadas": 2, "asignadas": 1, "sinDisponibilidad": 1}
        return {"evaluadas": 1, "asignadas": 1, "sinDisponibilidad": 0}

    monkeypatch.setattr(job_module.produccion_service, "asignar_pendientes_por_fecha", fake_asignar)

    summary = job_module.run_autoassign_today_once()

    assert summary == {
        "empresas": 2,
        "evaluadas": 3,
        "asignadas": 2,
        "sinDisponibilidad": 1,
        "locked": 0,
    }
    assert len(calls) == 2
    assert all(call["fecha_objetivo"] == date.today() for call in calls)
    assert fake_db.closed is True


def test_run_autoassign_today_once_skips_when_lock_is_busy(monkeypatch):
    fake_db = _FakeDb(scope_rows=[])

    monkeypatch.setattr(job_module, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(job_module, "_acquire_advisory_lock", lambda db: False)

    summary = job_module.run_autoassign_today_once()

    assert summary == {
        "empresas": 0,
        "evaluadas": 0,
        "asignadas": 0,
        "sinDisponibilidad": 0,
        "locked": 1,
    }
    assert fake_db.closed is True


def test_next_run_at_uses_same_day_future_slot():
    tz = ZoneInfo("America/Bogota")
    now = datetime(2026, 5, 13, 6, 0, tzinfo=tz)

    next_run = job_module._next_run_at(now, [time(6, 35), time(18, 45)])

    assert next_run == datetime(2026, 5, 13, 6, 35, tzinfo=tz)


def test_next_run_at_rolls_to_next_day_after_last_slot():
    tz = ZoneInfo("America/Bogota")
    now = datetime(2026, 5, 13, 19, 0, tzinfo=tz)

    next_run = job_module._next_run_at(now, [time(6, 35), time(18, 45)])

    assert next_run == datetime(2026, 5, 14, 6, 35, tzinfo=tz)
