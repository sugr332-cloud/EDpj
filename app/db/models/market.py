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

from sqlalchemy import JSON, BigInteger, DateTime, Integer, String, UniqueConstraint
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
