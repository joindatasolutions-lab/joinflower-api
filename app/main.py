import os
import traceback
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.extension import _rate_limit_exceeded_handler
from slowapi.middleware import SlowAPIMiddleware

from app.routers import pedido
from app.routers import catalogo
from app.routers import cliente
from app.routers import barrios
from app.routers import produccion
from app.routers import auth
from app.routers import domicilios
from app.routers import inventario
from app.routers import entregas
from app.middlewares.rate_limit import limiter
from sqlalchemy.exc import OperationalError
from app.database import engine

ALLOWED_ORIGINS = [
    "http://127.0.0.1:5500",
    "http://localhost:5500",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://localhost:3000",
]

app = FastAPI(
    title="PetalOps API",
    version="1.0.0"
)

# Rate limiting setup shared by all routers.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# 🔹 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🔹 Routers
app.include_router(catalogo.router)
app.include_router(pedido.router)
app.include_router(cliente.router)
app.include_router(barrios.router)
app.include_router(produccion.router)
app.include_router(auth.router)
app.include_router(domicilios.router)
app.include_router(inventario.router)
app.include_router(entregas.router)


@app.get("/")
def root():
    return {
        "message": "PetalOps API running",
        "docs": "/docs",
        "status": "ok"
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ping")
def ping():
    return {"message": "pong"}


# Endpoint temporal para probar conexión DB
@app.get("/db-connection")
def db_connection_check():
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            value = result.scalar()
        return {
            "ok": True,
            "result": value
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "trace": traceback.format_exc()
        }


if __name__ == "__main__":
    # Cloud Run injects PORT at runtime; default keeps local execution simple.
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port)