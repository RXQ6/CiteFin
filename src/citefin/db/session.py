"""Engine and session factories with bounded per-URL caching."""

from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def build_engine(database_url: str) -> Engine:
    """Create an engine suitable for PostgreSQL or local SQLite tests."""

    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, pool_pre_ping=True, connect_args=connect_args)


@lru_cache(maxsize=8)
def get_session_factory(database_url: str) -> sessionmaker[Session]:
    """Reuse connection pools without hiding the selected database URL."""

    return sessionmaker(bind=build_engine(database_url), expire_on_commit=False)
