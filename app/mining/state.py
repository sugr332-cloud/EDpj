"""Mining detectors — Phase 2-2.

Spec (IMPLEMENTATION_SPEC_V0.2.md §8.1, docs/PHASE_2_2_CANDIDATE_GENERATION_DESIGN_BASELINE_V0.1.md §2/§4):
`has_mining_cargo` needs a static is-this-commodity-ore classification
that didn't exist before Phase 2-2 (Phase 0-A's CargoState only ever
stored `commodity_name`/`quantity`). `mining_active`/`last_ring_body_id`
can't be read from a single event: `MiningRefined` doesn't carry a
BodyID/SystemAddress of its own, so the body context has to come from
whichever position-carrying event (`ApproachBody`/`Location`/`FSDJump`)
most recently preceded it.

`bodies.rings` is confirmed unavailable from Spansh's system-dump endpoint
(app/collectors/spansh.py), so this module never attempts a
static-ring-based "known ring" classification — only the player's own
MiningRefined history, exactly as IMPLEMENTATION_SPEC_V0.2.md §8.1 already
requires as the fallback.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.db.models.journal import JournalEvent
from app.db.models.player import CargoState
from app.journal import events as ev
from app.journal.extractor import strip_internal_name

# Not a game-balance number, just a classification of which commodities
# are obtained by mining (laser/core mining, Odyssey included) rather than
# manufactured/traded goods -- see design doc §4.1 for why this is exempt
# from the "never guess a value" rule. Internal (Market.json/EDDN) names,
# lowercase. Not necessarily exhaustive; extend as gaps are found.
MINABLE_COMMODITIES = frozenset(
    {
        "alexandrite",
        "bauxite",
        "benitoite",
        "bertrandite",
        "bromellite",
        "coltan",
        "cobalt",
        "cryolite",
        "gallite",
        "gold",
        "grandidierite",
        "indite",
        "lepidolite",
        "lithiumhydroxide",
        "lowtemperaturediamond",
        "methaneclathrate",
        "methanolmonohydratecrystals",
        "moissanite",
        "monazite",
        "musgravite",
        "osmium",
        "painite",
        "palladium",
        "platinum",
        "praseodymium",
        "rhodplumsite",
        "rutile",
        "samarium",
        "serendibite",
        "silver",
        "taaffeite",
        "tritium",
        "uraninite",
        "voidopal",
    }
)

# MiningRefined carries no position of its own; whichever of these most
# recently preceded it (by timestamp) supplies the body/system context.
_BODY_CONTEXT_EVENT_TYPES = (ev.APPROACH_BODY, ev.LOCATION, ev.FSD_JUMP)

DEFAULT_MINING_ACTIVE_LOOKBACK = dt.timedelta(minutes=15)


@dataclass(frozen=True)
class MiningContext:
    has_mining_cargo: bool
    ore_cargo: list[tuple[str, int]] = field(default_factory=list)  # (commodity_name, quantity)
    mining_active: bool = False
    last_ring_body_id: int | None = None
    last_ring_system_address: int | None = None
    # docs/PHASE_2_3_HORIZON_VALUE_DESIGN_BASELINE_V0.1.md §4.3 (v0.4):
    # the commodity of the same recent MiningRefined event used above --
    # not a separate query, just exposing a field already read here so
    # Value doesn't need to re-derive "what's being mined right now".
    last_refined_commodity: str | None = None
    # Reflects how the ring context was derived -- 1.0 when a real
    # MiningRefined + body-context pair was found, lower when mining is
    # inferred from cargo alone with no corroborating recent activity.
    # Not the final Recommendation confidence (that's a later stage).
    generation_confidence: float = 1.0


def _ore_cargo(session: Session) -> list[tuple[str, int]]:
    rows = session.query(CargoState).filter(CargoState.quantity > 0).all()
    return [(row.commodity_name, row.quantity) for row in rows if row.commodity_name in MINABLE_COMMODITIES]


def _find_recent_mining_refined(session: Session, since: dt.datetime) -> JournalEvent | None:
    # SQLite's DateTime(timezone=True) doesn't reliably compare a
    # timezone-aware bound parameter against its own naive-on-disk
    # representation (the same round-trip issue noted throughout this
    # project) -- strip tzinfo so the comparison is naive-vs-naive on
    # every dialect. `since` is always UTC by construction here.
    since_naive = since.replace(tzinfo=None) if since.tzinfo is not None else since
    candidates = (
        session.query(JournalEvent)
        .filter(JournalEvent.event_type == ev.MINING_REFINED)
        .order_by(JournalEvent.timestamp.desc())
        .limit(50)
        .all()
    )
    for event in candidates:
        event_time = event.timestamp.replace(tzinfo=None) if event.timestamp.tzinfo is not None else event.timestamp
        if event_time >= since_naive:
            return event
        break  # results are ordered desc; the first one below `since` ends the search
    return None


def _find_body_context_before(session: Session, timestamp: dt.datetime) -> JournalEvent | None:
    """Whichever ApproachBody/Location/FSDJump most recently precedes
    `timestamp` supplies the body/system MiningRefined itself doesn't
    carry. Same naive-comparison workaround as above, done in Python
    (not SQL) for the same reason."""
    ts_naive = timestamp.replace(tzinfo=None) if timestamp.tzinfo is not None else timestamp
    candidates = (
        session.query(JournalEvent)
        .filter(JournalEvent.event_type.in_(_BODY_CONTEXT_EVENT_TYPES))
        .order_by(JournalEvent.timestamp.desc())
        .limit(200)
        .all()
    )
    for event in candidates:
        event_time = event.timestamp.replace(tzinfo=None) if event.timestamp.tzinfo is not None else event.timestamp
        if event_time <= ts_naive and "BodyID" in event.payload:
            return event
    return None


def detect_mining_context(session: Session, lookback: dt.timedelta = DEFAULT_MINING_ACTIVE_LOOKBACK) -> MiningContext:
    ore_cargo = _ore_cargo(session)
    has_mining_cargo = len(ore_cargo) > 0

    since = dt.datetime.now(dt.timezone.utc) - lookback
    recent_refined = _find_recent_mining_refined(session, since)

    if recent_refined is None:
        return MiningContext(
            has_mining_cargo=has_mining_cargo,
            ore_cargo=ore_cargo,
            mining_active=False,
            last_ring_body_id=None,
            last_ring_system_address=None,
            generation_confidence=1.0 if not has_mining_cargo else 0.60,  # cargo alone, no corroborating activity
        )

    body_context = _find_body_context_before(session, recent_refined.timestamp)
    refined_type = recent_refined.payload.get("Type")
    return MiningContext(
        has_mining_cargo=has_mining_cargo,
        ore_cargo=ore_cargo,
        mining_active=True,
        last_ring_body_id=body_context.payload.get("BodyID") if body_context else None,
        last_ring_system_address=body_context.payload.get("SystemAddress") if body_context else None,
        last_refined_commodity=strip_internal_name(refined_type) if refined_type else None,
        generation_confidence=1.0 if body_context is not None else 0.75,
    )


@dataclass(frozen=True)
class RingLocation:
    system_address: int
    body_id: int
    refined_count: int


def find_historical_ring_locations(session: Session, limit: int = 5) -> list[RingLocation]:
    """Mining Start candidate ring discovery (design doc §4.4, priority 1
    only). Every distinct (system, body) the player has actually refined
    ore at, ranked by how often, using the same body-context join
    `detect_mining_context` uses per event.

    Design doc §4.4 also proposed a "priority 2" (guess ring-bearing
    bodies from Body.body_type/sub_type when there's no history). That is
    NOT implemented: verified against the live Spansh system-dump response
    (app/collectors/spansh.py), body records carry no field that indicates
    ring presence at all (only distance_to_arrival/type/subtype/landmarks/
    terraforming_state) -- there's nothing to guess from. With no history,
    mining_start simply generates no candidates, per design doc §4.4's own
    "両優先度0件の場合は候補を生成しない" fallback.
    """
    refined_events = (
        session.query(JournalEvent)
        .filter(JournalEvent.event_type == ev.MINING_REFINED)
        .order_by(JournalEvent.timestamp.asc())
        .all()
    )

    counts: dict[tuple[int, int], int] = {}
    for event in refined_events:
        body_context = _find_body_context_before(session, event.timestamp)
        if body_context is None:
            continue
        system_address = body_context.payload.get("SystemAddress")
        body_id = body_context.payload.get("BodyID")
        if system_address is None or body_id is None:
            continue
        key = (system_address, body_id)
        counts[key] = counts.get(key, 0) + 1

    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    return [RingLocation(system_address=k[0], body_id=k[1], refined_count=v) for k, v in ranked[:limit]]
