"""Bio detectors — Phase 2-2.

Spec (IMPLEMENTATION_SPEC_V0.2.md §8.2, docs/PHASE_2_2_CANDIDATE_GENERATION_DESIGN_BASELINE_V0.1.md §2/§5):

Two known gaps, documented rather than silently worked around:

  - `has_bio_signals` only sees `BodyBioSignal` rows sourced from EDDN's
    `fssbodysignals/1` (Phase 1). The player's own `FSSBodySignals`
    journal event is not yet merged into this table, so a body the
    player's own game has flagged bio signals on will not be detected
    here until it happens to be independently reported over EDDN.
  - "has the player personally scanned this body" cannot be determined at
    all (the `system_discovery`/`body_discovery` tables SPECIFICATION_V0.4.md
    §21 describes don't exist yet). Per design doc §5.2, this is never
    resolved to a hard "already scanned" exclusion — a body is always
    treated as not-yet-scanned, with `generation_confidence` lowered to
    reflect the uncertainty instead of asserting something unverifiable.

`find_nearby_bio_signal_bodies` only searches systems already cached
locally (`System` rows populated via Phase 1's on-demand Spansh lookups or
EDDN `journal/1` observations) — it does not trigger new Spansh fetches;
Phase 1's on-demand-only policy is unchanged (design doc §5.2).
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models.eddn import BodyBioSignal
from app.db.models.journal import JournalEvent
from app.db.models.static import System

SCAN_ORGANIC = "ScanOrganic"
SELL_ORGANIC_DATA = "SellOrganicData"
ANALYSE_SCAN_TYPE = "Analyse"  # the 3rd/final sample of a species completes it -- see SellOrganicData eligibility

# Never asserted as "already scanned"; this is the confidence penalty for
# not being able to check either way (design doc §5.2).
USER_UNSCANNED_UNKNOWN_CONFIDENCE = 0.60


def _naive(ts: dt.datetime) -> dt.datetime:
    return ts.replace(tzinfo=None) if ts.tzinfo is not None else ts


def bio_signals_for_body(session: Session, system_address: int, body_id: int) -> list[BodyBioSignal]:
    return session.query(BodyBioSignal).filter_by(system_address=system_address, body_id=body_id).all()


def has_bio_signals(session: Session, system_address: int, body_id: int) -> bool:
    return len(bio_signals_for_body(session, system_address, body_id)) > 0


def detect_unsold_bio_count(session: Session) -> int:
    """Approximate count of completed-but-unsold organic samples: how many
    `ScanOrganic` "Analyse" (species-completing) events happened since the
    last `SellOrganicData`. A simplification (design doc §5.3's "最小実装")
    -- it does not track per-species/per-body identity, just a count."""
    last_sell = (
        session.query(JournalEvent)
        .filter(JournalEvent.event_type == SELL_ORGANIC_DATA)
        .order_by(JournalEvent.timestamp.desc())
        .first()
    )
    since_naive = _naive(last_sell.timestamp) if last_sell is not None else None

    scans = (
        session.query(JournalEvent)
        .filter(JournalEvent.event_type == SCAN_ORGANIC)
        .order_by(JournalEvent.timestamp.asc())
        .all()
    )

    count = 0
    for scan in scans:
        if scan.payload.get("ScanType") != ANALYSE_SCAN_TYPE:
            continue
        if since_naive is not None and _naive(scan.timestamp) <= since_naive:
            continue
        count += 1
    return count


@dataclass(frozen=True)
class NearbyBioCandidate:
    system: System
    body_id: int
    signal_types: list[str]
    distance_ly: float


def find_nearby_bio_signal_bodies(
    session: Session, origin: System, distance_limit_ly: float
) -> list[NearbyBioCandidate]:
    candidates: list[NearbyBioCandidate] = []
    for system in session.query(System).all():
        if system.system_address == origin.system_address:
            continue
        distance = math.dist((origin.x, origin.y, origin.z), (system.x, system.y, system.z))
        if distance > distance_limit_ly:
            continue

        signals = session.query(BodyBioSignal).filter_by(system_address=system.system_address).all()
        if not signals:
            continue

        by_body: dict[int, list[str]] = {}
        for signal in signals:
            by_body.setdefault(signal.body_id, []).append(signal.signal_type)

        for body_id, signal_types in by_body.items():
            candidates.append(
                NearbyBioCandidate(system=system, body_id=body_id, signal_types=signal_types, distance_ly=distance)
            )
    return candidates
