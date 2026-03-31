from __future__ import annotations

import contextvars
import logging
import sys


_request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
_configured = False


class _RequestFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "request_id"):
            record.request_id = _request_id_ctx.get("-")
        if not hasattr(record, "module_name"):
            record.module_name = record.name
        return super().format(record)


def set_request_id(request_id: str) -> contextvars.Token:
    return _request_id_ctx.set(request_id)


def reset_request_id(token: contextvars.Token) -> None:
    _request_id_ctx.reset(token)


def get_request_id() -> str:
    return _request_id_ctx.get("-")


def configure_logging(level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        _RequestFormatter(
            fmt="%(asctime)s | %(levelname)s | %(module_name)s | %(request_id)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)

    _configured = True


def get_logger(module_name: str) -> logging.LoggerAdapter:
    base = logging.getLogger(f"app.{module_name}")
    return logging.LoggerAdapter(base, {"module_name": module_name})

