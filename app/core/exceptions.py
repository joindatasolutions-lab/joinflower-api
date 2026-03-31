from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.core.logger import get_logger


class APIError(Exception):
    def __init__(self, code: str, message: str, module: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.module = module
        self.status_code = status_code
        super().__init__(message)


def _module_from_path(path: str) -> str:
    p = (path or "").lower()
    if p.startswith("/pedido") or p.startswith("/pedidos"):
        return "pedido"
    if p.startswith("/produccion"):
        return "produccion"
    if p.startswith("/domicilios"):
        return "domicilios"
    if p.startswith("/auth"):
        return "auth"
    if p.startswith("/catalogo"):
        return "catalogo"
    if p.startswith("/pipeline"):
        return "pipeline"
    return "core"


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "-"))


def _error_payload(code: str, message: str, module: str, request_id: str) -> dict:
    return {
        "success": False,
        "error": {
            "code": code,
            "message": message,
            "module": module,
            "request_id": request_id,
        },
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def handle_api_error(request: Request, exc: APIError):
        logger = get_logger(exc.module)
        logger.warning("APIError [%s]: %s", exc.code, exc.message)
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(exc.code, exc.message, exc.module, _request_id(request)),
        )

    @app.exception_handler(HTTPException)
    async def handle_http_exception(request: Request, exc: HTTPException):
        module = _module_from_path(request.url.path)
        logger = get_logger(module)

        code = "HTTP_ERROR"
        message = str(exc.detail)
        if isinstance(exc.detail, dict):
            code = str(exc.detail.get("code") or "HTTP_ERROR")
            message = str(exc.detail.get("message") or message)
            module = str(exc.detail.get("module") or module)

        if int(exc.status_code) >= 500:
            logger.error("HTTPException [%s]: %s", code, message)
        else:
            logger.warning("HTTPException [%s]: %s", code, message)

        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(code, message, module, _request_id(request)),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(request: Request, exc: RequestValidationError):
        module = _module_from_path(request.url.path)
        logger = get_logger(module)
        logger.warning("Request validation error: %s", exc.errors())
        return JSONResponse(
            status_code=422,
            content=_error_payload(
                "VALIDATION_ERROR",
                "Datos de entrada invalidos",
                module,
                _request_id(request),
            ),
        )

    @app.exception_handler(ValidationError)
    async def handle_validation_error(request: Request, exc: ValidationError):
        module = _module_from_path(request.url.path)
        logger = get_logger(module)
        logger.warning("Validation error: %s", exc.errors())
        return JSONResponse(
            status_code=422,
            content=_error_payload(
                "VALIDATION_ERROR",
                "Datos de entrada invalidos",
                module,
                _request_id(request),
            ),
        )

    @app.exception_handler(SQLAlchemyError)
    async def handle_sqlalchemy_error(request: Request, exc: SQLAlchemyError):
        module = _module_from_path(request.url.path)
        logger = get_logger(module)
        logger.error("Database error", exc_info=True)
        return JSONResponse(
            status_code=500,
            content=_error_payload(
                "DATABASE_ERROR",
                "Error interno del servidor",
                module,
                _request_id(request),
            ),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception):
        module = _module_from_path(request.url.path)
        logger = get_logger(module)
        logger.error("Unhandled error", exc_info=True)
        return JSONResponse(
            status_code=500,
            content=_error_payload(
                "INTERNAL_SERVER_ERROR",
                "Error interno del servidor",
                module,
                _request_id(request),
            ),
        )
