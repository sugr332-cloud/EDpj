"""SQLAlchemy engine/session wiring.

Kept deliberately small for Phase 0-A: one engine, one sessionmaker, one
declarative Base that every model in app/db/models attaches to.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str | None = None):
    url = database_url or settings.database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args, future=True)


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
