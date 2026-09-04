from __future__ import annotations

import json
from pathlib import Path

from app.journal.extractor import docked_market_matches, extract_market_snapshot

FIXTURES = Path(__file__).parent.parent / "fixtures" / "state_files"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_extract_market_snapshot_produces_one_row_per_item():
    market = _load("Market.json")
    batch = extract_market_snapshot(market)
    assert batch.station_id == 128666762
    assert len(batch.rows) == 1
    row = batch.rows[0]
    assert row.commodity_name == "platinum"  # $platinum_name; stripped
    assert row.sell_price == 44586
    assert row.demand == 178
    assert row.source == "journal"


def test_docked_market_matches_same_market_id_and_close_time():
    docked = {"timestamp": "2026-01-01T12:15:00Z", "MarketID": 128666762}
    market = _load("Market.json")
    assert docked_market_matches(docked, market) is True


def test_docked_market_does_not_match_different_station():
    docked = {"timestamp": "2026-01-01T12:15:00Z", "MarketID": 999}
    market = _load("Market.json")
    assert docked_market_matches(docked, market) is False


def test_docked_market_does_not_match_when_stale():
    docked = {"timestamp": "2026-01-01T08:00:00Z", "MarketID": 128666762}
    market = _load("Market.json")
    assert docked_market_matches(docked, market) is False
