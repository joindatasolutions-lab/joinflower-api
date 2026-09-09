from __future__ import annotations

import os
import threading

from sqlalchemy import text

from app.core.logger import get_logger
from app.database import SessionLocal
from app.services import whatsapp_service

job_logger = get_logger("whatsapp_dispatch_job")

# Distinta de AUTOASSIGN_LOCK_KEY (2026051301) en produccion_autoassign_job.py -- cada job
# de fondo necesita su propia clave de advisory lock para no chocar entre si.
WHATSAPP_DISPATCH_LOCK_KEY = 2026082301


def _env_int(name: str, default: int, minimum: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or str(raw_value).strip() == "":
        return default
    try:
        value = int(str(raw_value).strip())
    except (TypeError, ValueError):
        job_logger.warning("Valor invalido para %s=%r. Usando default %s.", name, raw_value, default)
        return default
    if value < minimum:
        job_logger.warning("Valor fuera de rango para %s=%s. Minimo permitido %s.", name, value, minimum)
        return minimum
    return value


DEFAULT_INTERVAL_SECONDS = _env_int("WHATSAPP_DISPATCH_INTERVAL_SECONDS", default=30, minimum=5)
DEFAULT_BATCH_SIZE = _env_int("WHATSAPP_DISPATCH_BATCH_SIZE", default=20, minimum=1)


def whatsapp_dispatch_enabled() -> bool:
    return str(os.getenv("WHATSAPP_DISPATCH_ENABLED", "1")).strip().lower() not in {"0", "false", "no", "off"}


def _acquire_advisory_lock(db) -> bool:
    row = db.execute(
        text("SELECT pg_try_advisory_lock(:lock_key)"),
        {"lock_key": int(WHATSAPP_DISPATCH_LOCK_KEY)},
    ).first()
    return bool(row and row[0])


def _release_advisory_lock(db) -> None:
    db.execute(
        text("SELECT pg_advisory_unlock(:lock_key)"),
        {"lock_key": int(WHATSAPP_DISPATCH_LOCK_KEY)},
    )


def run_dispatch_once(batch_size: int = DEFAULT_BATCH_SIZE) -> int:
    """Procesa un lote de notificaciones pendientes. Protegido con advisory lock para que,
    si hay varias instancias de Cloud Run corriendo, solo una procese a la vez (evita envios
    duplicados -- ver Caso 7 del pedido original)."""
    db = SessionLocal()
    lock_acquired = False
    try:
        if not _acquire_advisory_lock(db):
            return 0
        lock_acquired = True
        return whatsapp_service.procesar_notificaciones_pendientes(db, limite=batch_size)
    except Exception:
        db.rollback()
        job_logger.exception("Error ejecutando el despacho de notificaciones de WhatsApp")
        return 0
    finally:
        if lock_acquired:
            try:
                _release_advisory_lock(db)
                db.commit()
            except Exception:
                db.rollback()
        db.close()


class WhatsAppDispatchJob:
    def __init__(self, interval_seconds: int = DEFAULT_INTERVAL_SECONDS, batch_size: int = DEFAULT_BATCH_SIZE):
        self.interval_seconds = max(interval_seconds, 5)
        self.batch_size = batch_size
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="whatsapp-dispatch-job",
            daemon=True,
        )
        self._thread.start()
        job_logger.info(
            "Job de despacho de WhatsApp iniciado. intervalo=%ss lote=%s",
            self.interval_seconds, self.batch_size,
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        job_logger.info("Job de despacho de WhatsApp detenido")

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                procesadas = run_dispatch_once(self.batch_size)
                if procesadas:
                    job_logger.info("Notificaciones de WhatsApp procesadas en este ciclo: %s", procesadas)
            except Exception:
                # Ya se registra el error dentro de run_dispatch_once.
                pass
            if self._stop_event.wait(self.interval_seconds):
                break
