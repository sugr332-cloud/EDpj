"""Historical Cargo Reconstruction — Phase 2-6F precondition.

Spec (docs/PHASE_2_6F_FORMULA_VALIDATION_GATE_DESIGN_BASELINE_V0.1.md §1/§2).
`CargoState` (app/db/models/player.py) is a live full-replacement
snapshot -- app/state/persist.py's own comment says as much ("a
full-replace snapshot, not an event log") -- so there is no historical
time series of held cargo anywhere else in this project (the same gap
Phase 2-6D's journal_replay.py already discovered and narrowed its own
scope around). Mining Sell/Continue's Value formulas depend on held
cargo quantity, so Historical Replay of those formulas is structurally
impossible without a T0-bounded reconstruction -- this module is that
reconstruction, kept read-only and separate from production state
(same pattern as journal_replay.py's reconstruct_player_state_at),
never touching app/state/persist.py or the live CargoState table.

Reconstruction is checkpoint + delta replay, not pure incremental
replay from an assumed empty start: the game's Journal (distinct from
the live Cargo.json side file app/state/reducer.py reads) periodically
logs a `Cargo` event carrying a full `Inventory` array -- confirmed
against this project's own real journal data (data/edpj.db,
2026-09-06). Without at least one such checkpoint at or before T0,
reconstruction returns None rather than guessing "empty" -- the same
"never fabricate missing data" principle as ValueResult/calibration
functions throughout this project.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from app.db.models.journal import JournalEvent
from app.journal.extractor import strip_internal_name
from app.mining.yield_model import EXPECTED_REFINED_QUANTITY_PER_EVENT

CARGO_CHECKPOINT_EVENT = "Cargo"

# Event types that change held cargo quantity between checkpoints, and
# how each one's payload maps to a (commodity, delta) pair.
_MINING_REFINED = "MiningRefined"
_MARKET_BUY = "MarketBuy"
_MARKET_SELL = "MarketSell"
_COLLECT_CARGO = "CollectCargo"
_EJECT_CARGO = "EjectCargo"
CARGO_DELTA_EVENT_TYPES = (_MINING_REFINED, _MARKET_BUY, _MARKET_SELL, _COLLECT_CARGO, _EJECT_CARGO)


class CargoReconstructionIntegrityError(Exception):
    """Raised when replaying delta events after the latest checkpoint
    would drive a commodity's quantity negative -- never silently
    clamped to 0, since that would mask a real data gap (e.g. a missing
    journal file in the backfill) as a clean reconstruction."""


def _delta_for(event: JournalEvent) -> tuple[str, int]:
    payload = event.payload
    if event.event_type == _MINING_REFINED:
        return strip_internal_name(payload["Type"]), int(EXPECTED_REFINED_QUANTITY_PER_EVENT)
    if event.event_type == _MARKET_BUY:
        return strip_internal_name(payload["Type"]), payload["Count"]
    if event.event_type == _MARKET_SELL:
        return strip_internal_name(payload["Type"]), -payload["Count"]
    if event.event_type == _COLLECT_CARGO:
        return strip_internal_name(payload["Type"]), 1
    if event.event_type == _EJECT_CARGO:
        return strip_internal_name(payload["Type"]), -payload["Count"]
    raise AssertionError(f"unreachable: {event.event_type} is not a cargo delta event")


def _latest_cargo_checkpoint_at_or_before(session: Session, t0: dt.datetime) -> JournalEvent | None:
    return (
        session.query(JournalEvent)
        .filter(JournalEvent.event_type == CARGO_CHECKPOINT_EVENT)
        .filter(JournalEvent.timestamp <= t0)
        .order_by(JournalEvent.timestamp.desc())
        .first()
    )


def _cargo_delta_events_between(session: Session, after: dt.datetime, upto: dt.datetime) -> list[JournalEvent]:
    return (
        session.query(JournalEvent)
        .filter(JournalEvent.event_type.in_(CARGO_DELTA_EVENT_TYPES))
        .filter(JournalEvent.timestamp > after)
        .filter(JournalEvent.timestamp <= upto)
        .order_by(JournalEvent.timestamp.asc())
        .all()
    )


def reconstruct_cargo_at_t0(session: Session, t0: dt.datetime) -> dict[str, int] | None:
    """None when no `Cargo` checkpoint exists at or before t0 -- this is
    "cannot reconstruct", never treated as "cargo was empty". Otherwise
    starts from the latest such checkpoint's `Inventory` and replays
    every cargo delta event strictly between the checkpoint and t0
    (inclusive of t0 itself, exclusive of the checkpoint's own instant)
    in chronological order. Events after t0 are never queried at all,
    so future leakage is structurally impossible rather than merely
    filtered out after the fact."""
    checkpoint = _latest_cargo_checkpoint_at_or_before(session, t0)
    if checkpoint is None:
        return None

    quantities: dict[str, int] = {}
    for row in checkpoint.payload.get("Inventory", []):
        quantities[strip_internal_name(row["Name"])] = row["Count"]

    for event in _cargo_delta_events_between(session, checkpoint.timestamp, t0):
        commodity, delta = _delta_for(event)
        new_quantity = quantities.get(commodity, 0) + delta
        if new_quantity < 0:
            raise CargoReconstructionIntegrityError(
                f"{commodity} would go negative ({new_quantity}) replaying {event.event_type} "
                f"at {event.timestamp} after checkpoint {checkpoint.timestamp}"
            )
        quantities[commodity] = new_quantity
    return quantities
