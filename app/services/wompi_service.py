import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from fastapi import HTTPException


WOMPI_CURRENCY = "COP"
WOMPI_CHECKOUT_BASE_URL = "https://checkout.wompi.co/p/"
WOMPI_TRANSACTIONS_BASE_URL = "https://api.wompi.co/v1/transactions"
logger = logging.getLogger(__name__)


def _get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise HTTPException(status_code=500, detail=f"Falta variable de entorno requerida: {name}")
    return value


def _build_query(params: list[tuple[str, str | int]]) -> str:
    return "&".join(f"{key}={quote_plus(str(value))}" for key, value in params)


def _validate_redirect_url(redirect_url: str | None) -> str | None:
    candidate = (redirect_url or "").strip()
    if not candidate:
        return None

    lowered = candidate.lower()
    if not lowered.startswith("https://"):
        raise ValueError("WOMPI_REDIRECT_URL must use HTTPS.")

    if "localhost" in lowered or "127.0.0.1" in lowered:
        raise ValueError("WOMPI_REDIRECT_URL cannot point to localhost.")

    if "yourdomain.com" in lowered or "example.com" in lowered:
        raise ValueError("WOMPI_REDIRECT_URL cannot use placeholder domains.")

    return candidate


def generate_reference(pedido_id: int) -> str:
    seconds = int(time.time())
    millis = int(datetime.now(tz=timezone.utc).timestamp() * 1000) % 1000
    return f"pedido_{int(pedido_id)}_{seconds}{millis:03d}"


def calculate_amount_in_cents(total: Decimal | float | int | None) -> int:
    value = Decimal(str(total or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(value * 100)


def generate_integrity_signature(reference: str, amount_in_cents: int) -> str:
    integrity_secret = _get_required_env("WOMPI_INTEGRITY_SECRET")
    signature_string = f"{reference}{int(amount_in_cents)}{WOMPI_CURRENCY}{integrity_secret}"
    return hashlib.sha256(signature_string.encode("utf-8")).hexdigest()


def build_checkout_url(reference: str, amount_in_cents: int, email: str) -> str:
    public_key = _get_required_env("WOMPI_PUBLIC_KEY")
    redirect_url = _validate_redirect_url(os.getenv("WOMPI_REDIRECT_URL"))

    customer_email = (email or "").strip()
    if not customer_email:
        raise HTTPException(status_code=400, detail="email es obligatorio para checkout WOMPI")

    signature_hash = generate_integrity_signature(reference=reference, amount_in_cents=amount_in_cents)

    params: list[tuple[str, str | int]] = [
        ("public-key", public_key),
        ("currency", WOMPI_CURRENCY),
        ("amount-in-cents", int(amount_in_cents)),
        ("reference", reference),
        ("signature:integrity", signature_hash),
        ("customer-data:email", customer_email),
    ]

    if redirect_url:
        logger.info("WOMPI redirect URL: %s", redirect_url)
        params.append(("redirect-url", redirect_url))

    base_url = WOMPI_CHECKOUT_BASE_URL.rstrip("?")
    return f"{base_url}?{_build_query(params)}"


def map_wompi_status(provider_status: str) -> str:
    status = (provider_status or "").strip().upper()
    if status == "APPROVED":
        return "approved"
    if status in {"DECLINED", "VOIDED", "ERROR"}:
        return "declined"
    return "pending"


def verify_wompi_transaction(transaction_id: str) -> dict:
    tx_id = (transaction_id or "").strip()
    if not tx_id:
        raise HTTPException(status_code=400, detail="id es obligatorio")

    private_key = _get_required_env("WOMPI_PRIVATE_KEY")
    request = Request(
        url=f"{WOMPI_TRANSACTIONS_BASE_URL}/{tx_id}",
        headers={
            "Authorization": f"Bearer {private_key}",
            "Accept": "application/json",
        },
        method="GET",
    )

    try:
        with urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"WOMPI verification failed with HTTP {exc.code}",
        )
    except URLError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"WOMPI verification failed: {exc.reason}",
        )

    data = payload.get("data") or {}
    provider_status = str(data.get("status") or "").upper()

    return {
        "id": tx_id,
        "status": map_wompi_status(provider_status),
        "providerStatus": provider_status,
    }
