import os
from urllib.parse import quote_plus, urlencode

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


# Configuracion directa para pruebas locales (solo cuando se ejecuta como script).
if __name__ == "__main__":
    os.environ["DATABASE_HOST"] = "136.119.27.100"
    os.environ["DATABASE_USER"] = "joindata"
    os.environ["DATABASE_PASSWORD"] = "Emprender2026#"
    os.environ["DATABASE_NAME"] = "joinflower-dev"
    os.environ["DATABASE_PORT"] = "5432"

load_dotenv()


# Permitir ambas convenciones de variables (DATABASE_* y DB_*).
DB_HOST = os.getenv("DATABASE_HOST") or os.getenv("DB_HOST")
DB_PORT = os.getenv("DATABASE_PORT") or os.getenv("DB_PORT")
DB_NAME = os.getenv("DATABASE_NAME") or os.getenv("DB_NAME")
DB_USER = os.getenv("DATABASE_USER") or os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DATABASE_PASSWORD") or os.getenv("DB_PASSWORD")
INSTANCE_CONNECTION_NAME = (
    os.getenv("INSTANCE_CONNECTION_NAME")
    or os.getenv("CLOUD_SQL_CONNECTION_NAME")
    or os.getenv("DB_INSTANCE_CONNECTION_NAME")
)
DB_SOCKET_DIR = os.getenv("DB_SOCKET_DIR", "/cloudsql")


def _build_database_url() -> str:
    raw_database_url = str(os.getenv("DATABASE_URL", "")).strip()
    if raw_database_url:
        return raw_database_url

    encoded_password = quote_plus(DB_PASSWORD or "")

    # Cloud Run + Cloud SQL Unix socket.
    if INSTANCE_CONNECTION_NAME:
        socket_host = f"{DB_SOCKET_DIR.rstrip('/')}/{INSTANCE_CONNECTION_NAME}"
        query = urlencode({"host": socket_host})
        return f"postgresql+psycopg2://{DB_USER}:{encoded_password}@/{DB_NAME}?{query}"

    # Support direct socket path in DB_HOST/DATABASE_HOST.
    if DB_HOST and str(DB_HOST).startswith("/"):
        query = urlencode({"host": str(DB_HOST)})
        return f"postgresql+psycopg2://{DB_USER}:{encoded_password}@/{DB_NAME}?{query}"

    if DB_PORT and str(DB_PORT).lower() != "none":
        return f"postgresql+psycopg2://{DB_USER}:{encoded_password}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

    return f"postgresql+psycopg2://{DB_USER}:{encoded_password}@{DB_HOST}/{DB_NAME}"


DATABASE_URL = _build_database_url()


engine = create_engine(
    DATABASE_URL,
    connect_args={"options": "-csearch_path=petalops"},
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=1800,
    pool_pre_ping=True,
    echo=False,
)


if __name__ == "__main__":
    try:
        from sqlalchemy import text

        with engine.connect() as conn:
            result = conn.execute(text("SELECT version();"))
            print("Conexion exitosa a la base de datos:", result.fetchone())
    except Exception as e:
        print("Error al conectar a la base de datos:", e)


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
