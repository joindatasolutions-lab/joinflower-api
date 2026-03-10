import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv
from urllib.parse import quote_plus

load_dotenv()


# Permitir ambas convenciones de variables (DATABASE_* y DB_*)
DB_HOST = os.getenv("DATABASE_HOST") or os.getenv("DB_HOST")
DB_PORT = os.getenv("DATABASE_PORT") or os.getenv("DB_PORT")
DB_NAME = os.getenv("DATABASE_NAME") or os.getenv("DB_NAME")
DB_USER = os.getenv("DATABASE_USER") or os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DATABASE_PASSWORD") or os.getenv("DB_PASSWORD")

# Preferir DATABASE_URL completa si está presente
raw_database_url = str(os.getenv("DATABASE_URL", "")).strip()
if raw_database_url:
    DATABASE_URL = raw_database_url
else:
    encoded_password = quote_plus(DB_PASSWORD or "")
    # Solo agregar puerto si está definido y válido
    if DB_PORT and DB_PORT.lower() != "none":
        DATABASE_URL = (
            f"mysql+pymysql://{DB_USER}:{encoded_password}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
        )
    else:
        DATABASE_URL = (
            f"mysql+pymysql://{DB_USER}:{encoded_password}@{DB_HOST}/{DB_NAME}"
        )

engine = create_engine(
    DATABASE_URL,
    # Connection pool tuned for multi-tenant API workload.
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=1800,
    pool_pre_ping=True,
    echo=False
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()