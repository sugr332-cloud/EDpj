"""Ship cargo capacity — Phase 2-3.

Spec (docs/PHASE_2_3_HORIZON_VALUE_DESIGN_BASELINE_V0.1.md §4.3, v0.4).

Not a new "Loadout parsing" feature: Phase 0-A's parser/extractor already
stores every journal line verbatim in `journal_events` regardless of event
type (app/journal/parser.py/extractor.py), so the `Loadout` event's
`CargoCapacity` field is already sitting in the DB the moment a Loadout
event has been ingested — this just reads it back.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models.journal import JournalEvent
from app.journal import events as ev


def get_cargo_capacity(session: Session) -> int | None:
    """None only when no `Loadout` event has ever been recorded, or the
    most recent one is missing/malformed. `CargoCapacity=0` is a valid
    ship state (no cargo racks fitted) and must never be conflated with
    "unknown" -- callers distinguish via `is None`, not truthiness."""
    event = (
        session.query(JournalEvent)
        .filter(JournalEvent.event_type == ev.LOADOUT)
        .order_by(JournalEvent.timestamp.desc(), JournalEvent.id.desc())
        .first()
    )
    if event is None:
        return None
    return event.payload.get("CargoCapacity")
