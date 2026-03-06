from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import pedido
from app.routers import catalogo
from app.routers import cliente
from app.routers import barrios
from app.routers import produccion

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

# 🔹 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
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