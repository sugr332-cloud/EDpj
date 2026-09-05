"""SQLAlchemy engine/session wiring.

Kept deliberately small for Phase 0-A: one engine, one sessionmaker, one
declarative Base that every model in app/db/models attaches to.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str | None = None):
    url = database_url or settings.database_url
    kwargs: dict = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url:
            # A plain in-memory sqlite engine hands each new thread its own
            # (empty) database via SQLAlchemy's default pool — breaking
            # anything that touches the session from another thread, e.g.
            # FastAPI's TestClient (endpoints run in a worker thread pool).
            # StaticPool keeps one shared connection alive for the whole
            # engine regardless of thread.
            kwargs["poolclass"] = StaticPool
    return create_engine(url, future=True, **kwargs)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_db(bind_engine=None) -> None:
    """Create all tables. Phase 0-A has no Alembic migration history yet to
    replay in tests, so this is the primary bootstrap path; `migrations/`
    takes over once the schema needs to evolve without dropping data."""
    from app.db import models  # noqa: F401  (ensure models are registered)

    Base.metadata.create_all(bind=bind_engine or engine)


@contextmanager
def session_scope(session_factory=None) -> Iterator[Session]:
    factory = session_factory or SessionLocal
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
