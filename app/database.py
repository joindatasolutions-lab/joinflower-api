import os
from urllib.parse import quote_plus, urlencode

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


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
DB_POOL_SIZE = max(1, int(os.getenv("DB_POOL_SIZE", "3")))
DB_MAX_OVERFLOW = max(0, int(os.getenv("DB_MAX_OVERFLOW", "2")))
DB_POOL_TIMEOUT = max(5, int(os.getenv("DB_POOL_TIMEOUT", "30")))
DB_POOL_RECYCLE = max(60, int(os.getenv("DB_POOL_RECYCLE", "1800")))


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
    pool_size=DB_POOL_SIZE,
    max_overflow=DB_MAX_OVERFLOW,
    pool_timeout=DB_POOL_TIMEOUT,
    pool_recycle=DB_POOL_RECYCLE,
    pool_pre_ping=True,
    echo=False,
)


if __name__ == "__main__":
    try:
        from sqlalchemy import text

        required_settings = {
            "DATABASE_HOST": DB_HOST,
            "DATABASE_NAME": DB_NAME,
            "DATABASE_USER": DB_USER,
            "DATABASE_PASSWORD": DB_PASSWORD,
        }
        missing = [key for key, value in required_settings.items() if not value]
        if missing and not INSTANCE_CONNECTION_NAME:
            raise RuntimeError(
                "Faltan variables de entorno para conectar a la base de datos: "
                + ", ".join(missing)
            )

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
