"""Singleton player state + current cargo snapshot.

Spec (IMPLEMENTATION_SPEC_V0.2 section 7.3): `player_state` is a singleton
row (id is always 1); `cargo_state` is fully replaced each time Cargo.json
(or a journal cargo event) is reduced, so it always reflects "what's in the
hold right now" rather than an event log.

`source_status` records per-source NO_DATA/STALE/OK flags (section 4.2:
missing/incomplete/unreadable state files must degrade gracefully, not stop
the process) — kept as a small JSON blob instead of three separate columns
so Phase 1 can add more sources without a migration.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

SINGLETON_ID = 1


class PlayerState(Base):
    __tablename__ = "player_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=SINGLETON_ID)

    current_system: Mapped[str | None] = mapped_column(String, nullable=True)
    current_system_address: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    current_body_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    current_body_name: Mapped[str | None] = mapped_column(String, nullable=True)
    current_station_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    current_station_name: Mapped[str | None] = mapped_column(String, nullable=True)
    current_ship_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    credits: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    fuel_main: Mapped[float | None] = mapped_column(Float, nullable=True)
    cargo_tons: Mapped[int | None] = mapped_column(Integer, nullable=True)

    docked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    landed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    on_foot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    source_status: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: dt.datetime.now(dt.timezone.utc)
    )


class CargoState(Base):
    __tablename__ = "cargo_state"

    commodity_name: Mapped[str] = mapped_column(String, primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: dt.datetime.now(dt.timezone.utc)
    )
