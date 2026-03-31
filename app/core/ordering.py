from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")

PRIORITY_RANK = {
    "CRITICA": 5,
    "CRÍTICA": 5,
    "URGENTE": 4,
    "ALTA": 3,
    "MEDIA": 2,
    "BAJA": 1,
}


def _to_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def priority_rank(value: str | None) -> int:
    return PRIORITY_RANK.get(str(value or "").strip().upper(), 0)


def sort_operativo(
    items: Iterable[T],
    *,
    due_at: Callable[[T], datetime | None],
    priority: Callable[[T], str | None],
) -> list[T]:
    now = datetime.now(timezone.utc)

    def key(item: T) -> tuple[int, float, int]:
        due = _to_utc(due_at(item))
        is_atrasado = 1 if (due is not None and due < now) else 0
        tiempo_restante = (due - now).total_seconds() if due is not None else float("inf")
        prioridad = priority_rank(priority(item))
        return (-is_atrasado, tiempo_restante, -prioridad)

    return sorted(list(items), key=key)

