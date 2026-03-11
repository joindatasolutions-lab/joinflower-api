import json
import time
from typing import Any

# In-memory TTL cache shared by app workers.
# Each key stores: (expiration_epoch_seconds, serialized_json_payload)
_MEMORY_CACHE: dict[str, tuple[float, str]] = {}


def get_cache(key: str) -> Any | None:
    """Read a cached value from in-memory store with TTL validation."""
    safe_key = str(key or "").strip()
    if not safe_key:
        return None

    entry = _MEMORY_CACHE.get(safe_key)
    if not entry:
        return None

    expires_at, payload = entry
    if expires_at <= time.time():
        _MEMORY_CACHE.pop(safe_key, None)
        return None

    try:
        return json.loads(payload)
    except Exception:
        _MEMORY_CACHE.pop(safe_key, None)
        return None


def set_cache(key: str, value: Any, ttl: int) -> None:
    """Store a cache entry in memory with TTL (seconds)."""
    safe_key = str(key or "").strip()
    if not safe_key:
        return

    ttl_seconds = max(int(ttl or 0), 1)
    payload = json.dumps(value, ensure_ascii=True, default=str)

    _MEMORY_CACHE[safe_key] = (time.time() + ttl_seconds, payload)
