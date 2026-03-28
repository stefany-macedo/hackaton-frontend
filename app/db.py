from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass
from contextlib import contextmanager

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import declarative_base, sessionmaker, Session

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"

load_dotenv(dotenv_path=ENV_PATH)


@dataclass
class Settings:
    api_title: str = os.getenv("API_TITLE", "Hackaton API")
    api_version: str = os.getenv("API_VERSION", "0.1.0")

    POSTGRES_DB: str = os.getenv("POSTGRES_DB", "postgres")
    POSTGRES_USER: str = os.getenv("POSTGRES_USER", "")
    POSTGRES_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "")
    POSTGRES_HOST: str = os.getenv("POSTGRES_HOST", "")
    POSTGRES_PORT: str = os.getenv("POSTGRES_PORT", "5432")
    POSTGRES_SSLMODE: str = os.getenv("POSTGRES_SSLMODE", "require")


settings = Settings()

print("API_TITLE =", settings.api_title)
print("API_VERSION =", settings.api_version)
print("POSTGRES_DB =", settings.POSTGRES_DB)
print("POSTGRES_USER =", settings.POSTGRES_USER)
print("POSTGRES_HOST =", settings.POSTGRES_HOST)
print("POSTGRES_PORT =", settings.POSTGRES_PORT)
print("POSTGRES_SSLMODE =", settings.POSTGRES_SSLMODE)

database_url = URL.create(
    drivername="postgresql+psycopg2",
    username=settings.POSTGRES_USER,
    password=settings.POSTGRES_PASSWORD,
    host=settings.POSTGRES_HOST,
    port=int(settings.POSTGRES_PORT),
    database=settings.POSTGRES_DB,
    query={"sslmode": settings.POSTGRES_SSLMODE},
)

engine = create_engine(
    database_url,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=Session,
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


@contextmanager
def db_session():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()