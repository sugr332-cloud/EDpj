from __future__ import annotations

import pytest
from sqlalchemy.orm import sessionmaker

from app.db.session import Base, make_engine


@pytest.fixture()
def db_session():
    """Fresh in-memory SQLite DB per test — Phase 0-A models avoid any
    Postgres-only types, so this is a faithful stand-in for the real
    docker-compose Postgres during unit/integration tests."""
    engine = make_engine("sqlite:///:memory:")
    from app.db import models  # noqa: F401  (register model metadata)

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = factory()
    try:
        yield session
    finally:
        session.close()
