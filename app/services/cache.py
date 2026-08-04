import json
import os
import time
from typing import Any

from app.core.logger import get_logger

logger = get_logger("cache")

# Fase 1 (memoria, Redis-ready): backend actual siempre "memory".
# CACHE_BACKEND queda documentado para cuando se agregue el backend Redis en fase 2.
CACHE_BACKEND = os.getenv("CACHE_BACKEND", "memory")
CACHE_DEFAULT_TTL = max(int(os.getenv("CACHE_DEFAULT_TTL", "300")), 1)
CACHE_DEBUG = str(os.getenv("CACHE_DEBUG", "false")).strip().lower() in ("1", "true", "yes")

# In-memory TTL cache shared by app workers.
# Each key stores: (expiration_epoch_seconds, serialized_json_payload)
_MEMORY_CACHE: dict[str, tuple[float, str]] = {}

logger.info(
    "Cache inicializado: backend=%s default_ttl=%ss debug=%s",
    CACHE_BACKEND,
    CACHE_DEFAULT_TTL,
    CACHE_DEBUG,
)


def cache_ttl(name: str, default: int | None = None) -> int:
    """Resuelve el TTL (segundos) de un caché con nombre, permitiendo override por env CACHE_TTL_<NAME>."""
    env_value = os.getenv(f"CACHE_TTL_{name.strip().upper()}")
    if env_value is not None:
        try:
            return max(int(env_value), 1)
        except ValueError:
            logger.warning("CACHE_TTL_%s invalido (%r), usando default", name.upper(), env_value)

    return max(int(default if default is not None else CACHE_DEFAULT_TTL), 1)


def get_cache(key: str) -> Any | None:
    """Read a cached value from in-memory store with TTL validation."""
    safe_key = str(key or "").strip()
    if not safe_key:
        return None

    entry = _MEMORY_CACHE.get(safe_key)
    if not entry:
        if CACHE_DEBUG:
            logger.info("cache miss key=%s", safe_key)
        return None

    expires_at, payload = entry
    if expires_at <= time.time():
        _MEMORY_CACHE.pop(safe_key, None)
        if CACHE_DEBUG:
            logger.info("cache expired key=%s", safe_key)
        return None

    try:
        value = json.loads(payload)
    except Exception:
        _MEMORY_CACHE.pop(safe_key, None)
        return None

    if CACHE_DEBUG:
        logger.info("cache hit key=%s", safe_key)
    return value


def set_cache(key: str, value: Any, ttl: int) -> None:
    """Store a cache entry in memory with TTL (seconds)."""
    safe_key = str(key or "").strip()
    if not safe_key:
        return

    ttl_seconds = max(int(ttl or 0), 1)
    try:
        payload = json.dumps(value, ensure_ascii=True, default=str)
    except (TypeError, ValueError):
        logger.warning("cache set omitido, payload no serializable key=%s", safe_key)
        return

    _MEMORY_CACHE[safe_key] = (time.time() + ttl_seconds, payload)
    if CACHE_DEBUG:
        logger.info("cache set key=%s ttl=%ss", safe_key, ttl_seconds)


def invalidate_cache_prefix(prefix: str) -> None:
    safe_prefix = str(prefix or "").strip()
    if not safe_prefix:
        return

    removed = 0
    for key in list(_MEMORY_CACHE.keys()):
        if key.startswith(safe_prefix):
            _MEMORY_CACHE.pop(key, None)
            removed += 1

    if CACHE_DEBUG and removed:
        logger.info("cache invalidated prefix=%s removed=%s", safe_prefix, removed)
