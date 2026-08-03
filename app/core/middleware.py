from __future__ import annotations

from uuid import uuid4

from fastapi import Request
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logger import reset_empresa_id, reset_request_id, set_empresa_id, set_request_id
from app.core.security import JWT_ALGORITHM, JWT_SECRET


REQUEST_ID_HEADER = "X-Request-ID"


def _extract_empresa_id_for_logs(request: Request) -> str:
    """Lee el empresaID del JWT solo para etiquetar logs (best-effort, nunca bloquea la request).
    La autorizacion real sigue a cargo de get_current_auth_context."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.lower().startswith("bearer "):
        return "-"
    token = auth_header[7:].strip()
    if not token:
        return "-"
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return "-"
    empresa_id = payload.get("empresaID")
    return str(empresa_id) if empresa_id is not None else "-"


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid4())
        request.state.request_id = request_id
        request_id_token = set_request_id(request_id)
        empresa_id_token = set_empresa_id(_extract_empresa_id_for_logs(request))
        try:
            response = await call_next(request)
        finally:
            reset_request_id(request_id_token)
            reset_empresa_id(empresa_id_token)

        response.headers[REQUEST_ID_HEADER] = request_id
        return response

