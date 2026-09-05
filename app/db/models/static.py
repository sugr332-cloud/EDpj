"""Static galaxy data (systems / bodies / stations / commodities).

Spec (IMPLEMENTATION_SPEC_V0.2.md §7.1): populated on-demand from Spansh
(app/collectors/spansh.py) as systems are actually visited/relevant —
Phase 1 deliberately does not bulk-import the galaxy dump (see
IMPLEMENTATION_SPEC_V0.2.md §5.3's existing "Phase 0でSpansh body/station
importは必須にしない" stance, extended into Phase 1's on-demand design).

`system_address`/`body_id64`/`station_id` are Elite Dangerous's/Spansh's
own real identifiers (SystemAddress, body id64, MarketID) — not locally
assigned sequences — so they're the primary keys directly, matching how
`MarketSnapshot.station_id` already uses the real MarketID.

`commodity_id` IS a locally assigned sequence (no single universal numeric
commodity id exists across tools); `internal_name` (e.g. "platinum",
matching `MarketSnapshot.commodity_name`) is the natural/stable key.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class System(Base):
    __tablename__ = "systems"

    system_address: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    x: Mapped[float] = mapped_column(Float, nullable=False)
    y: Mapped[float] = mapped_column(Float, nullable=False)
    z: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)  # 'spansh' | 'journal'
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: dt.datetime.now(dt.timezone.utc)
    )


class Body(Base):
    __tablename__ = "bodies"

    body_id64: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    system_address: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    body_type: Mapped[str | None] = mapped_column(String, nullable=True)
    sub_type: Mapped[str | None] = mapped_column(String, nullable=True)
    distance_to_arrival_ls: Mapped[float | None] = mapped_column(Float, nullable=True)
    gravity: Mapped[float | None] = mapped_column(Float, nullable=True)
    radius: Mapped[float | None] = mapped_column(Float, nullable=True)
    atmosphere: Mapped[str | None] = mapped_column(String, nullable=True)
    landable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Ring type / inner radius / outer radius / composition, when present.
    # NO_DATA (absent key), never a guessed placeholder — IMPLEMENTATION_SPEC_V0.2.md §7.1.
    rings: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False)  # 'spansh'
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: dt.datetime.now(dt.timezone.utc)
    )


class Station(Base):
    __tablename__ = "stations"

    station_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Elite Dangerous MarketID
    system_address: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    station_type: Mapped[str | None] = mapped_column(String, nullable=True)
    distance_to_arrival_ls: Mapped[float | None] = mapped_column(Float, nullable=True)
    landing_pad: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {"small":.., "medium":.., "large":..}
    has_vista_genomics: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_fleet_carrier: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source: Mapped[str] = mapped_column(String, nullable=False)  # 'spansh'
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: dt.datetime.now(dt.timezone.utc)
    )


class Commodity(Base):
    __tablename__ = "commodities"
    __table_args__ = (UniqueConstraint("internal_name", name="uq_commodity_internal_name"),)

    commodity_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    internal_name: Mapped[str] = mapped_column(String, nullable=False)  # e.g. "platinum"
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False)  # 'eddn' | 'spansh'
