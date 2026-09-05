"""Turns parsed journal lines / raw state-file payloads into DB rows.

Kept separate from parser.py (which only tokenizes journal lines) and from
state/reducer.py (which folds events into the player_state/cargo_state
singleton) so each piece is independently testable.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from app.db.models.journal import JournalEvent
from app.db.models.market import MarketSnapshot
from app.journal.parser import ParsedLine, parse_journal_timestamp


def to_journal_event(line: ParsedLine) -> JournalEvent:
    return JournalEvent(
        file_name=line.file_name,
        line_number=line.line_number,
        event_type=line.event_type,
        timestamp=line.timestamp,
        payload=line.payload,
    )


def strip_internal_name(name: str) -> str:
    """Market.json commodity `Name` is already the bare internal name
    (e.g. "platinum"); some journal payloads instead carry the `$x_name;`
    form. Normalize to the bare form so both agree on one key. Public
    because app/mining/state.py also normalizes MiningRefined's `Type`
    field the same way."""
    if name.startswith("$") and name.endswith("_name;"):
        return name[1 : -len("_name;")]
    return name


@dataclass(frozen=True)
class MarketSnapshotBatch:
    station_id: int
    observed_at: dt.datetime
    rows: list[MarketSnapshot]


def extract_market_snapshot(
    market_payload: dict, received_at: dt.datetime | None = None, source: str = "journal"
) -> MarketSnapshotBatch:
    """Convert a raw Market.json payload into one MarketSnapshot row per
    commodity line. Spec (SPECIFICATION_V0.4 section 4.1): captured on
    Docked because Market.json is overwritten on the next dock."""
    received_at = received_at or dt.datetime.now(dt.timezone.utc)
    station_id = market_payload["MarketID"]
    # Market.json uses the same lowercase "timestamp" key as journal lines
    # and Status.json/Cargo.json (not "Timestamp").
    observed_at = parse_journal_timestamp(market_payload["timestamp"])

    rows = [
        MarketSnapshot(
            station_id=station_id,
            commodity_name=strip_internal_name(item["Name"]),
            buy_price=item.get("BuyPrice", 0),
            sell_price=item.get("SellPrice", 0),
            supply=item.get("Supply", 0),
            demand=item.get("Demand", 0),
            observed_at=observed_at,
            received_at=received_at,
            source=source,
            raw_payload=item,
        )
        for item in market_payload.get("Items", [])
    ]
    return MarketSnapshotBatch(station_id=station_id, observed_at=observed_at, rows=rows)


def docked_market_matches(docked_payload: dict, market_payload: dict, tolerance: dt.timedelta = dt.timedelta(minutes=10)) -> bool:
    """True if a Market.json snapshot plausibly corresponds to a given
    Docked event: same MarketID, and captured within `tolerance` of the
    dock. Backfill only ever sees the *current* Market.json (it gets
    overwritten on each dock), so this is how we decide whether it's safe
    to attribute that file's contents to a specific historical Docked
    line rather than a later, unrelated dock."""
    if docked_payload.get("MarketID") != market_payload.get("MarketID"):
        return False
    docked_at = parse_journal_timestamp(docked_payload["timestamp"])
    observed_at = parse_journal_timestamp(market_payload["timestamp"])
    return abs(observed_at - docked_at) <= tolerance
