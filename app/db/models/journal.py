"""Raw journal event persistence.

Spec (IMPLEMENTATION_SPEC_V0.2 section 4.1): each journal line is stored
verbatim in `payload`; uniqueness is on (file_name, line_number) so
re-running backfill over the same files never duplicates rows. Timestamps
are parsed as UTC and never converted to local time before storage/compare.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class JournalEvent(Base):
    __tablename__ = "journal_events"
    __table_args__ = (UniqueConstraint("file_name", "line_number", name="uq_journal_file_line"),)

    # Integer (not BigInteger) is deliberate: SQLite only treats a PK column
    # as its ROWID alias — and thus autoincrements it — when it's declared
    # exactly INTEGER PRIMARY KEY; BIGINT PRIMARY KEY does not qualify and
    # leaves `id` NULL on insert. 32-bit autoincrement is plenty for a
    # single-player journal history.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    timestamp: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    inserted_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: dt.datetime.now(dt.timezone.utc)
    )
