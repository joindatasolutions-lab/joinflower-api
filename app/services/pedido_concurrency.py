"""Concurrency primitives. Reservations and results belong to the business transaction."""
import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import text


def begin_creation(db, request, *, empresa_id: int, operation: str, payload):
    key = request.headers.get("Idempotency-Key", "").strip()
    if not key or len(key) > 128:
        raise HTTPException(422, detail={"code": "IDEMPOTENCY_KEY_REQUIRED", "message": "Envia Idempotency-Key (1 a 128 caracteres)."})
    serialized = json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    params = {"empresa": empresa_id, "operation": operation, "key": key,
              "hash": hashlib.sha256(serialized.encode()).hexdigest()}
    inserted = db.execute(text("""
        INSERT INTO petalops.pedido_operacion (empresa_id, operacion, clave, payload_hash)
        VALUES (:empresa, :operation, :key, :hash)
        ON CONFLICT (empresa_id, operacion, clave) DO NOTHING
        RETURNING clave
    """), params).first()
    if inserted:
        return params, None
    row = db.execute(text("""
        SELECT payload_hash, respuesta_json FROM petalops.pedido_operacion
        WHERE empresa_id = :empresa AND operacion = :operation AND clave = :key
        FOR UPDATE
    """), params).mappings().one()
    if row["payload_hash"] != params["hash"]:
        raise HTTPException(409, detail={"code": "IDEMPOTENCY_KEY_REUSED", "message": "La clave ya corresponde a otra solicitud."})
    if row["respuesta_json"] is None:
        # Never recreate blindly if an older deployment committed an incomplete reservation.
        raise HTTPException(409, detail={"code": "OPERATION_INCOMPLETE", "message": "La operacion requiere recuperacion antes de reintentar."})
    return params, json.loads(row["respuesta_json"])


def complete_creation(db, reservation, result):
    db.execute(text("""
        UPDATE petalops.pedido_operacion SET respuesta_json = :response
        WHERE empresa_id = :empresa AND operacion = :operation AND clave = :key
    """), {**reservation, "response": json.dumps(result, ensure_ascii=True)})


def check_and_increment_version(pedido, expected: int):
    """Caller must hold the order's row lock until commit/rollback."""
    current = int(pedido.version or 1)
    if expected != current:
        raise HTTPException(409, detail={"code": "PEDIDO_VERSION_CONFLICT", "versionActual": current,
                                         "message": "El pedido cambio. Recarga antes de guardar."})
    pedido.version = current + 1
