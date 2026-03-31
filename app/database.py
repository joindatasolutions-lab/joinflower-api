import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv
from urllib.parse import quote_plus


# Configuración directa para pruebas locales (sobrescribe .env si se ejecuta como script)
if __name__ == "__main__":
    os.environ["DATABASE_HOST"] = "136.119.27.100"
    os.environ["DATABASE_USER"] = "joindata"
    os.environ["DATABASE_PASSWORD"] = "Emprender2026#"
    os.environ["DATABASE_NAME"] = "joinflower-dev"
    os.environ["DATABASE_PORT"] = "5432"

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
    # Cambia aquí para usar PostgreSQL
    encoded_password = quote_plus(DB_PASSWORD or "")
    if DB_PORT and DB_PORT.lower() != "none":
        DATABASE_URL = (
            f"postgresql+psycopg2://{DB_USER}:{encoded_password}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
        )
    else:
        DATABASE_URL = (
            f"postgresql+psycopg2://{DB_USER}:{encoded_password}@{DB_HOST}/{DB_NAME}"
        )


# Crear el engine usando connect_args para establecer search_path a petalops
engine = create_engine(
    DATABASE_URL,
    connect_args={"options": "-csearch_path=petalops"},
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=1800,
    pool_pre_ping=True,
    echo=False
)


# Prueba de conexión rápida
if __name__ == "__main__":
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version();"))
            print("Conexión exitosa a la base de datos:", result.fetchone())
    except Exception as e:
        print("Error al conectar a la base de datos:", e)

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
    except Exception:
        db.rollback()  
        raise
    finally:
        db.close()