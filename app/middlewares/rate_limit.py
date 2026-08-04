import os

from slowapi import Limiter
from slowapi.util import get_remote_address

# Fase 1 (memoria, Redis-ready): backend actual siempre "memory://" por instancia.
# RATE_LIMIT_STORAGE_URI queda documentado para cuando se agregue Redis en fase 2
# (mismo Redis que respaldaria el cache, ver pendientes/Mejoras/cache-fase1-memoria-segura.md).
RATE_LIMIT_STORAGE_URI = os.getenv("RATE_LIMIT_STORAGE_URI", "memory://")

limiter = Limiter(key_func=get_remote_address, storage_uri=RATE_LIMIT_STORAGE_URI)


def rate_limit(name: str, default: str) -> str:
    """Resuelve un limite (ej. '10/minute') permitiendo override por env RATE_LIMIT_<NAME>."""
    return os.getenv(f"RATE_LIMIT_{name.strip().upper()}", default)
