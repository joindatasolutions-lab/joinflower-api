from __future__ import annotations

import os
import re

DEFAULT_ALLOWED_ORIGINS = [
    "http://127.0.0.1:5500",
    "http://localhost:5500",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:5175",
    "http://127.0.0.1:3000",
    "http://localhost:3000",
    "https://petalops.joindata.com.co",
    "https://adminpetalops.joindata.com.co",
    "https://domiapp.joindata.com.co",
]

LOCAL_ORIGIN_REGEX = r"https?://(localhost|127\.0\.0\.1)(:\d+)?$"


def get_allowed_origins() -> list[str]:
    extra_origins = [
        origin.strip()
        for origin in os.getenv("ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    ]
    return [*DEFAULT_ALLOWED_ORIGINS, *extra_origins]


def is_allowed_origin(origin: str | None) -> bool:
    if not origin:
        return False
    clean_origin = str(origin).strip()
    return clean_origin in get_allowed_origins() or re.fullmatch(LOCAL_ORIGIN_REGEX, clean_origin) is not None


def add_cors_headers_for_origin(headers, origin: str | None) -> None:
    if not is_allowed_origin(origin):
        return
    headers["Access-Control-Allow-Origin"] = str(origin).strip()
    headers["Access-Control-Allow-Credentials"] = "true"
    headers["Vary"] = "Origin"
