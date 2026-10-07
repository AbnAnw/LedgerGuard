"""SQLAlchemy engine and session lifecycle."""

from collections.abc import Generator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from ledgerguard.config import get_settings


def build_engine(database_url: str | None = None) -> Engine:
    """Build a connection-pooled PostgreSQL engine without connecting eagerly."""

    url = database_url or get_settings().database_url
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 2})


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """Provide a transaction-capable session to request handlers."""

    with SessionLocal() as session:
        yield session
