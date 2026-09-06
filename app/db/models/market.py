"""Market snapshot persistence.

Spec (SPECIFICATION_V0.4 section 4.1 / 6, IMPLEMENTATION_SPEC_V0.2 section
7.2): Market.json is captured on the `Docked` event because the file is
overwritten on the next dock. Phase 0-A only writes source='journal'; EDDN
(source='eddn') arrives in Phase 1 and shares this table — `source` +
`observed_at`/`received_at` keep the two apart.

Phase 0-A has no static `commodities` table yet (that lands with Phase 1
Spansh import), so commodities are keyed by their journal-internal name
(e.g. "platinum") rather than a commodity_id FK. `commodity_id` is left in
as a nullable column so a later migration can backfill it without a schema
break.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, BigInteger, Date, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "station_id", "commodity_name", "observed_at", "source", name="uq_market_snapshot_observation"
        ),
    )

    # Integer PK, not BigInteger — see app/db/models/journal.py for why
    # (SQLite only autoincrements a column declared exactly INTEGER
    # PRIMARY KEY). station_id below stays BigInteger since it holds
    # Elite Dangerous's real MarketID values, not a local sequence.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    station_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    commodity_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    commodity_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    buy_price: Mapped[int] = mapped_column(Integer, nullable=False)
    sell_price: Mapped[int] = mapped_column(Integer, nullable=False)
    supply: Mapped[int] = mapped_column(Integer, nullable=False)
    demand: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    received_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: dt.datetime.now(dt.timezone.utc)
    )
    source: Mapped[str] = mapped_column(String, nullable=False, index=True)  # 'journal' | 'eddn'
    raw_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class MarketLatest(Base):
    """(station_id, commodity_name) -> most recent observation, upserted
    (IMPLEMENTATION_SPEC_V0.2.md §7.2: "MVPではmaterialized view refresh
    に依存せず upsert する"). The upsert must only overwrite when the
    incoming `observed_at` is newer than what's stored — EDDN delivery
    order isn't guaranteed — see app/collectors/eddn.py."""

    __tablename__ = "market_latest"
    __table_args__ = (UniqueConstraint("station_id", "commodity_name", name="uq_market_latest_station_commodity"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    station_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    commodity_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    buy_price: Mapped[int] = mapped_column(Integer, nullable=False)
    sell_price: Mapped[int] = mapped_column(Integer, nullable=False)
    supply: Mapped[int] = mapped_column(Integer, nullable=False)
    demand: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)  # 'journal' | 'eddn'


class StationActivity(Base):
    """Raw observation count + last_observed_at per station. Deliberately
    does NOT bake fixed 1h/6h/24h windows into columns — those are
    query-time aggregations over `market_snapshots.observed_at`, kept
    flexible rather than fixed at the schema level (per review feedback
    on this table's design)."""

    __tablename__ = "station_activity"
    __table_args__ = (UniqueConstraint("station_id", name="uq_station_activity_station"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    station_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    observation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_observed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MarketHistoricalObservation(Base):
    """Phase 2-5A (docs/PHASE_2_5A_MARKET_PREDICTABILITY_IMPLEMENTATION_BASELINE_V0.1.md
    §5): a narrow, on-demand cache of rows extracted from the historical
    EDDN archive (https://edgalaxydata.space/EDDN/) -- only rows matching
    a (station_id, commodity_name) that was actually queried, never a
    galaxy-wide import. `commodity_name` matches MarketLatest's existing
    key convention, not the spec's commodity_id (never populated
    anywhere in this project).

    `buy_price`/`supply`/`received_at` (Phase 2-6F-T1,
    docs/PHASE_2_6F_T1_TRADE_MARKET_PERSISTENCE_DESIGN_BASELINE_V0.1.md
    §2) are nullable: `app/collectors/eddn.py`'s parse_commodity_message()
    already extracts them from the raw archive envelope, but
    ensure_days_fetched_batch() discarded them before this Trade-specific
    need existed. NULL means "observed before these columns were
    tracked", never backfilled as 0 or any other guess -- existing rows
    stay NULL until (if ever) their date range is deliberately
    re-fetched."""

    __tablename__ = "market_historical_observations"
    __table_args__ = (
        UniqueConstraint(
            "station_id", "commodity_name", "observed_at", name="uq_market_historical_observation"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    station_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    commodity_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    sell_price: Mapped[int] = mapped_column(Integer, nullable=False)
    demand: Mapped[int] = mapped_column(Integer, nullable=False)
    buy_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    supply: Mapped[int | None] = mapped_column(Integer, nullable=True)
    observed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    received_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MarketHistoricalFetchLog(Base):
    """Records that (station_id, commodity_name, date) has already been
    scanned from the archive, independent of how many (if any) matching
    rows that day produced -- a day with zero matches would otherwise
    look identical to "never fetched" if only MarketHistoricalObservation
    row counts were consulted, causing a pointless re-download every time
    (§5)."""

    __tablename__ = "market_historical_fetch_log"
    __table_args__ = (
        UniqueConstraint("station_id", "commodity_name", "date", name="uq_market_historical_fetch_log"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    station_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    commodity_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    fetched_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: dt.datetime.now(dt.timezone.utc)
    )


class MarketPredictability(Base):
    """Phase 2-5A: derived price-predictability classification for one
    (station_id, commodity_name), computed from
    MarketHistoricalObservation over one analysis window. Never persists
    per-observation data itself -- only the aggregate statistics and
    classification. `volatility_class` is price-only (docs/PHASE_2_5A...
    §7); demand volatility is kept as diagnostic columns, not folded into
    classification."""

    __tablename__ = "market_predictability"
    __table_args__ = (
        UniqueConstraint(
            "station_id", "commodity_name", "window_end", name="uq_market_predictability_target_window"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    station_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    commodity_name: Mapped[str] = mapped_column(String, nullable=False, index=True)

    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    window_start: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    median_abs_price_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    p95_abs_price_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    median_abs_demand_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    p95_abs_demand_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    median_observation_gap_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    p95_observation_gap_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    volatility_class: Mapped[str] = mapped_column(String, nullable=False)  # STABLE|MODERATE|VOLATILE|INSUFFICIENT
    model_version: Mapped[str] = mapped_column(String, nullable=False)
    computed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: dt.datetime.now(dt.timezone.utc)
    )
