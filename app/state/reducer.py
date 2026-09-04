"""Folds journal events + Status/Cargo/Market state files into the
singleton `player_state` / `cargo_state` rows.

Spec (IMPLEMENTATION_SPEC_V0.2 section 4.3): "Journal と state files を統合し
て singleton player_state と cargo_state を更新する." Journal events carry
where the player is (system/body/station, docked/landed transitions);
Status.json carries fast-changing numeric state (fuel, credits) that isn't
reliably present in journal events at every moment. State files always win
for the fields they own — they represent "right now", while journal events
are folded chronologically to reconstruct position/docked state that
Status.json doesn't fully capture on its own (e.g. current system name).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Iterable

from app.collectors.state_files import StateFileResult
from app.journal import events as ev

# Status.json Flags bitfield (subset relevant to Phase 0-A).
FLAG_DOCKED = 1 << 0
FLAG_LANDED = 1 << 1
# Status.json Flags2 bitfield (Odyssey on-foot state).
FLAG2_ON_FOOT = 1 << 0


@dataclass
class JournalEventLike:
    """Minimal shape reduce_events() needs — satisfied by both the ORM
    JournalEvent model and app.journal.parser.ParsedLine, so the reducer
    doesn't care whether state is being rebuilt from DB rows or from a
    fresh backfill pass."""

    file_name: str
    line_number: int
    timestamp: dt.datetime
    event_type: str
    payload: dict


@dataclass
class ReducedPlayerState:
    fields: dict = field(default_factory=dict)
    source_status: dict = field(default_factory=dict)
    cargo_rows: list[dict] = field(default_factory=list)


def _sort_key(e: JournalEventLike):
    return (e.timestamp, e.file_name, e.line_number)


def reduce_journal_event(event_type: str, payload: dict) -> dict:
    """One event -> partial player_state field updates. Unknown/irrelevant
    event types return {} rather than raising, since the backfill stream
    contains hundreds of event types Phase 0-A doesn't need."""
    if event_type == ev.LOAD_GAME:
        updates = {}
        if "ShipID" in payload:
            updates["current_ship_id"] = payload["ShipID"]
        return updates

    if event_type == ev.LOADOUT:
        return {"current_ship_id": payload.get("ShipID")}

    if event_type in (ev.LOCATION, ev.FSD_JUMP):
        updates = {
            "current_system": payload.get("StarSystem"),
            "current_system_address": payload.get("SystemAddress"),
            "docked": bool(payload.get("Docked", False)),
        }
        if "BodyID" in payload:
            updates["current_body_id"] = payload["BodyID"]
        if "Body" in payload:
            updates["current_body_name"] = payload["Body"]
        if updates["docked"]:
            updates["current_station_id"] = payload.get("MarketID")
            updates["current_station_name"] = payload.get("StationName")
        else:
            updates["current_station_id"] = None
            updates["current_station_name"] = None
        return updates

    if event_type == ev.DOCKED:
        return {
            "docked": True,
            "current_station_id": payload.get("MarketID"),
            "current_station_name": payload.get("StationName"),
            "current_system": payload.get("StarSystem"),
            "current_system_address": payload.get("SystemAddress"),
        }

    if event_type == ev.UNDOCKED:
        return {"docked": False, "current_station_id": None, "current_station_name": None}

    if event_type == ev.SUPERCRUISE_ENTRY:
        return {"landed": False}

    if event_type == ev.SUPERCRUISE_EXIT:
        updates = {}
        if "BodyID" in payload:
            updates["current_body_id"] = payload["BodyID"]
        if "Body" in payload:
            updates["current_body_name"] = payload["Body"]
        return updates

    if event_type == ev.TOUCHDOWN:
        updates = {"landed": True}
        if "BodyID" in payload:
            updates["current_body_id"] = payload["BodyID"]
        if "Body" in payload:
            updates["current_body_name"] = payload["Body"]
        return updates

    if event_type == ev.LIFTOFF:
        return {"landed": False}

    if event_type == ev.APPROACH_BODY:
        updates = {}
        if "BodyID" in payload:
            updates["current_body_id"] = payload["BodyID"]
        if "Body" in payload:
            updates["current_body_name"] = payload["Body"]
        return updates

    if event_type == ev.LEAVE_BODY:
        return {}

    return {}


def reduce_events(events: Iterable[JournalEventLike]) -> dict:
    """Chronological fold. Later events overwrite earlier ones for any
    field they touch; fields no event ever set are simply absent."""
    state: dict = {}
    for e in sorted(events, key=_sort_key):
        state.update(reduce_journal_event(e.event_type, e.payload))
    return state


def reduce_status(payload: dict) -> dict:
    flags = payload.get("Flags", 0) or 0
    flags2 = payload.get("Flags2", 0) or 0
    updates = {
        "docked": bool(flags & FLAG_DOCKED),
        "landed": bool(flags & FLAG_LANDED),
        "on_foot": bool(flags2 & FLAG2_ON_FOOT),
    }
    fuel = payload.get("Fuel") or {}
    if "FuelMain" in fuel:
        updates["fuel_main"] = fuel["FuelMain"]
    if "Balance" in payload:
        updates["credits"] = payload["Balance"]
    return updates


def reduce_cargo(payload: dict) -> list[dict]:
    """Cargo.json 'Inventory' -> a full replacement set for cargo_state.
    Empty/zero-quantity entries are dropped rather than stored as zero
    rows."""
    rows = []
    for item in payload.get("Inventory", []):
        qty = item.get("Count", 0)
        if qty <= 0:
            continue
        rows.append({"commodity_name": item["Name"].lower(), "quantity": qty})
    return rows


def build_reduced_state(
    events: Iterable[JournalEventLike],
    status: StateFileResult,
    cargo: StateFileResult,
) -> ReducedPlayerState:
    fields = reduce_events(events)
    source_status = {"status_json": status.status, "cargo_json": cargo.status}

    if status.status == "ok" and status.data is not None:
        fields.update(reduce_status(status.data))

    cargo_rows: list[dict] = []
    if cargo.status == "ok" and cargo.data is not None:
        cargo_rows = reduce_cargo(cargo.data)
        fields["cargo_tons"] = sum(row["quantity"] for row in cargo_rows)

    return ReducedPlayerState(fields=fields, source_status=source_status, cargo_rows=cargo_rows)
