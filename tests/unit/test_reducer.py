from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from app.collectors.state_files import StateFileResult
from app.state.reducer import (
    JournalEventLike,
    build_reduced_state,
    reduce_cargo,
    reduce_events,
    reduce_status,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "state_files"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_reduce_status_extracts_docked_flag():
    status = _load("Status.json")
    updates = reduce_status(status)
    assert updates["docked"] is True
    assert updates["landed"] is False
    assert updates["on_foot"] is False
    assert updates["fuel_main"] == 8.0
    assert updates["credits"] == 950000


def test_reduce_cargo_drops_zero_quantity_rows():
    rows = reduce_cargo({"Inventory": [{"Name": "platinum", "Count": 5}, {"Name": "gold", "Count": 0}]})
    assert rows == [{"commodity_name": "platinum", "quantity": 5}]


def test_reduce_events_folds_chronologically_by_timestamp_then_line():
    events = [
        JournalEventLike(
            file_name="a.log",
            line_number=2,
            timestamp=dt.datetime(2026, 1, 1, 12, 5, tzinfo=dt.timezone.utc),
            event_type="FSDJump",
            payload={"StarSystem": "Deciat", "SystemAddress": 1, "Docked": False},
        ),
        JournalEventLike(
            file_name="a.log",
            line_number=1,
            timestamp=dt.datetime(2026, 1, 1, 12, 0, tzinfo=dt.timezone.utc),
            event_type="LoadGame",
            payload={"ShipID": 7},
        ),
        JournalEventLike(
            file_name="a.log",
            line_number=3,
            timestamp=dt.datetime(2026, 1, 1, 12, 15, tzinfo=dt.timezone.utc),
            event_type="Docked",
            payload={"StarSystem": "Deciat", "SystemAddress": 1, "MarketID": 42, "StationName": "Farseer Inc"},
        ),
    ]
    state = reduce_events(events)
    assert state["current_ship_id"] == 7
    assert state["current_system"] == "Deciat"
    assert state["docked"] is True
    assert state["current_station_id"] == 42


def test_build_reduced_state_reconstructs_full_snapshot():
    events = [
        JournalEventLike(
            file_name="a.log",
            line_number=1,
            timestamp=dt.datetime(2026, 1, 1, 12, 15, tzinfo=dt.timezone.utc),
            event_type="Docked",
            payload={"StarSystem": "Deciat", "SystemAddress": 1, "MarketID": 42, "StationName": "Farseer Inc"},
        ),
    ]
    status = StateFileResult(status="ok", data=_load("Status.json"), path=Path("Status.json"))
    cargo = StateFileResult(status="ok", data=_load("Cargo.json"), path=Path("Cargo.json"))

    reduced = build_reduced_state(events, status, cargo)

    assert reduced.fields["current_system"] == "Deciat"
    assert reduced.fields["docked"] is True
    assert reduced.fields["fuel_main"] == 8.0
    assert reduced.fields["cargo_tons"] == 5
    assert reduced.source_status == {"status_json": "ok", "cargo_json": "ok"}
    assert reduced.cargo_rows == [{"commodity_name": "platinum", "quantity": 5}]


def test_build_reduced_state_degrades_gracefully_on_missing_files():
    status = StateFileResult(status="no_data", data=None, path=Path("Status.json"))
    cargo = StateFileResult(status="no_data", data=None, path=Path("Cargo.json"))

    reduced = build_reduced_state([], status, cargo)

    assert reduced.source_status == {"status_json": "no_data", "cargo_json": "no_data"}
    assert reduced.cargo_rows == []
    assert "fuel_main" not in reduced.fields
