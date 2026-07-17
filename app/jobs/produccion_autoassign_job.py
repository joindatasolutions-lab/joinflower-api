from __future__ import annotations

import os
import threading
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.core.timezone import colombia_today
from app.core.logger import get_logger
from app.database import SessionLocal
from app.models.produccion import Produccion
from app.services import produccion_service


job_logger = get_logger("produccion_autoassign_job")
AUTOASSIGN_LOCK_KEY = 2026051301
DEFAULT_TIMEZONE = os.getenv("PRODUCCION_AUTOASSIGN_TIMEZONE", "America/Bogota")
DEFAULT_SCHEDULE = os.getenv("PRODUCCION_AUTOASSIGN_SCHEDULE", "06:35,18:45")


def autoassign_job_enabled() -> bool:
    return str(os.getenv("PRODUCCION_AUTOASSIGN_ENABLED", "1")).strip().lower() not in {"0", "false", "no", "off"}


def _parse_schedule_times(raw_value: str | None) -> list[time]:
    raw_items = [item.strip() for item in str(raw_value or "").split(",") if item.strip()]
    parsed: list[time] = []
    for item in raw_items:
        try:
            hour_str, minute_str = item.split(":", 1)
            parsed.append(time(hour=int(hour_str), minute=int(minute_str)))
        except Exception as exc:  # pragma: no cover - defensive path
            raise ValueError(f"Horario inválido para PRODUCCION_AUTOASSIGN_SCHEDULE: {item}") from exc
    if not parsed:
        parsed = [time(hour=6, minute=35), time(hour=18, minute=45)]
    return sorted(parsed)


def _resolve_timezone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except Exception:
        job_logger.warning("Zona horaria inválida para autoasignación: %s. Usando UTC.", timezone_name)
        return ZoneInfo("UTC")


def _next_run_at(now: datetime, schedule_times: list[time]) -> datetime:
    if now.tzinfo is None:
        raise ValueError("El cálculo de próxima ejecución requiere datetime con zona horaria")
    for scheduled_time in schedule_times:
        candidate = datetime.combine(now.date(), scheduled_time, tzinfo=now.tzinfo)
        if candidate > now:
            return candidate
    return datetime.combine(now.date() + timedelta(days=1), schedule_times[0], tzinfo=now.tzinfo)


def _seconds_until_next_run(now: datetime, schedule_times: list[time]) -> float:
    next_run = _next_run_at(now, schedule_times)
    delta = next_run - now
    return max(delta.total_seconds(), 1.0)


def _acquire_advisory_lock(db) -> bool:
    row = db.execute(
        text("SELECT pg_try_advisory_lock(:lock_key)"),
        {"lock_key": int(AUTOASSIGN_LOCK_KEY)},
    ).first()
    return bool(row and row[0])


def _release_advisory_lock(db) -> None:
    db.execute(
        text("SELECT pg_advisory_unlock(:lock_key)"),
        {"lock_key": int(AUTOASSIGN_LOCK_KEY)},
    )


def run_autoassign_today_once() -> dict[str, int]:
    db = SessionLocal()
    lock_acquired = False
    try:
        if not _acquire_advisory_lock(db):
            return {"empresas": 0, "evaluadas": 0, "asignadas": 0, "sinDisponibilidad": 0, "locked": 1}

        lock_acquired = True
        estados = produccion_service._resolve_estado_produccion_ids(db)
        today = colombia_today()

        scope_rows = (
            db.query(Produccion.empresaID, Produccion.sucursalID)
            .filter(
                Produccion.fechaProgramadaProduccion == today,
                Produccion.estado == estados["pendiente"],
                Produccion.floristaID.is_(None),
            )
            .group_by(Produccion.empresaID, Produccion.sucursalID)
            .order_by(Produccion.empresaID.asc(), Produccion.sucursalID.asc())
            .all()
        )

        resumen = {
            "empresas": len(scope_rows),
            "evaluadas": 0,
            "asignadas": 0,
            "sinDisponibilidad": 0,
            "locked": 0,
        }

        for empresa_id, sucursal_id in scope_rows:
            stats = produccion_service.asignar_pendientes_por_fecha(
                db=db,
                empresa_id=int(empresa_id),
                sucursal_id=(int(sucursal_id) if sucursal_id is not None else None),
                fecha_objetivo=today,
                incluir_vencidas=False,
                usuario="job.autoassign.today",
                motivo="Asignación automática programada de pendientes de hoy",
            )
            resumen["evaluadas"] += int(stats["evaluadas"])
            resumen["asignadas"] += int(stats["asignadas"])
            resumen["sinDisponibilidad"] += int(stats["sinDisponibilidad"])

        db.commit()
        if resumen["evaluadas"] > 0:
            job_logger.info(
                "Autoasignación programada ejecutada. empresas=%s evaluadas=%s asignadas=%s sinDisponibilidad=%s",
                resumen["empresas"],
                resumen["evaluadas"],
                resumen["asignadas"],
                resumen["sinDisponibilidad"],
            )
        return resumen
    except Exception:
        db.rollback()
        job_logger.exception("Error ejecutando autoasignación programada de producción")
        raise
    finally:
        if lock_acquired:
            try:
                _release_advisory_lock(db)
                db.commit()
            except Exception:
                db.rollback()
        db.close()


class ProduccionAutoassignJob:
    def __init__(self, timezone_name: str = DEFAULT_TIMEZONE, schedule_raw: str = DEFAULT_SCHEDULE):
        self.timezone_name = timezone_name
        self.timezone = _resolve_timezone(timezone_name)
        self.schedule_times = _parse_schedule_times(schedule_raw)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="produccion-autoassign-job",
            daemon=True,
        )
        self._thread.start()
        job_logger.info(
            "Job de autoasignación de producción iniciado. timezone=%s horarios=%s",
            self.timezone.key,
            ",".join(slot.strftime("%H:%M") for slot in self.schedule_times),
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        job_logger.info("Job de autoasignación de producción detenido")

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            now = datetime.now(self.timezone)
            wait_seconds = _seconds_until_next_run(now, self.schedule_times)
            if self._stop_event.wait(wait_seconds):
                break
            try:
                run_autoassign_today_once()
            except Exception:
                # Logged inside run_autoassign_today_once.
                pass
