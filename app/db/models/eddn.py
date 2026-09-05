"""EDDN network-wide observations, kept structurally separate from the
player's own `journal_events`.

Spec (SPECIFICATION_V0.4.md §13.2 / IMPLEMENTATION_SPEC_V0.2.md §14.2):
EDDN's `journal/1` schema relays a filtered subset of *other* commanders'
journal-like events (exploration-focused: FSSDiscoveryScan,
FSSAllBodiesFound, Scan, etc.) across the whole network — a different
thing from the player's own Journal (`journal_events`, Phase 0-A), which
drives the state reducer and timing extractor. Mixing the two into one
table risks EDDN data being picked up by code that assumes every row is
"me" (e.g. the state reducer's `event_type.in_(STATE_RELEVANT_EVENTS)`
queries) — so `eddn_journal_observations` is a separate table, and Phase 1
does not feed it into `player_state`/`cargo_state` at all. It exists as a
general-purpose exploration observation log for Phase 3's "has anyone
found bio signals here" candidate generation.

`BodyBioSignal` is upserted (latest-known-state), not an event log —
signal type/count per body is effectively static once discovered, unlike
market prices — but keeps `first_observed_at`/`last_observed_at` rather
than collapsing to a single timestamp, since "how fresh/how long known"
may matter later. A full historical log is not built in Phase 1.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, BigInteger, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class EddnJournalObservation(Base):
    __tablename__ = "eddn_journal_observations"
    __table_args__ = (
        UniqueConstraint("system_address", "event_type", "observed_at", "uploader_id", name="uq_eddn_journal_obs"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    system_address: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    # BodyID as carried in the raw event (small, system-scoped) — not
    # Spansh's global body_id64 (app/db/models/static.py's Body table).
    body_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    observed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    received_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: dt.datetime.now(dt.timezone.utc)
    )
    # Defaults to "" rather than NULL so it stays part of the effective
    # dedup key on every dialect (NULL != NULL breaks uniqueness checks).
    uploader_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)


class BodyBioSignal(Base):
    __tablename__ = "body_bio_signals"
    __table_args__ = (
        UniqueConstraint("system_address", "body_id", "signal_type", name="uq_body_bio_signal"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    system_address: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    body_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    signal_type: Mapped[str] = mapped_column(String, nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)  # 'eddn' | 'journal'
    first_observed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_observed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: dt.datetime.now(dt.timezone.utc)
    )
