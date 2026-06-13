import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.extension import _rate_limit_exceeded_handler
from slowapi.middleware import SlowAPIMiddleware

from app.core.exceptions import register_exception_handlers
from app.core.logger import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.database import engine
from app.jobs.produccion_autoassign_job import ProduccionAutoassignJob, autoassign_job_enabled
from app.middlewares.rate_limit import limiter
from app.routers import auth
from app.routers import barrios
from app.routers import catalogo
from app.routers import cliente
from app.routers import contabilidad
from app.routers import domicilios
from app.routers import entregas
from app.routers import inventario
from app.routers import pedido
from app.routers import pipeline
from app.routers import produccion

configure_logging()

ALLOWED_ORIGINS = [
    "http://127.0.0.1:5500",
    "http://localhost:5500",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://localhost:3000",
    "https://petalops.joindata.com.co",
]

extra_origins = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]
if extra_origins:
    ALLOWED_ORIGINS.extend(extra_origins)

_produccion_autoassign_job = ProduccionAutoassignJob()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if autoassign_job_enabled():
        _produccion_autoassign_job.start()
    try:
        yield
    finally:
        if autoassign_job_enabled():
            _produccion_autoassign_job.stop()


app = FastAPI(
    title="PetalOps API",
    version="1.0.0",
    lifespan=lifespan,
)

register_exception_handlers(app)

# Rate limiting setup shared by all routers.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(RequestContextMiddleware)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(catalogo.router)
app.include_router(pedido.router)
app.include_router(cliente.router)
app.include_router(contabilidad.router)
app.include_router(barrios.router)
app.include_router(produccion.router)
app.include_router(auth.router)
app.include_router(domicilios.router)
app.include_router(inventario.router)
app.include_router(entregas.router)
app.include_router(pipeline.router)


@app.get("/")
def root():
    return {
        "message": "PetalOps API running",
        "docs": "/docs",
        "status": "ok",
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ping")
def ping():
    return {"message": "pong"}


@app.get("/db-connection")
def db_connection_check():
    try:
        from sqlalchemy import text

        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            value = result.scalar()
        return {
            "ok": True,
            "result": value,
        }
    except Exception:
        return {
            "ok": False,
            "error": "database unavailable",
        }


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port)
