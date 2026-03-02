from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import pedido
from app.routers import catalogo
from app.routers import cliente
from app.routers import barrios

ALLOWED_ORIGINS = [
    "http://127.0.0.1:5500",
    "http://localhost:5500",
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