"""Bio candidate generation — Phase 2-2.

Spec (IMPLEMENTATION_SPEC_V0.2.md §8.3, docs/PHASE_2_2_CANDIDATE_GENERATION_DESIGN_BASELINE_V0.1.md §5).

Per design doc §1.1: candidates requiring `supercruise` (bio_next_system,
bio_return) are generated regardless of `supercruise` currently being
`unavailable` -- that's Horizon's problem, not this module's.

`bio_return`'s target uses `MiningTarget`'s shape (station_name/system_name/
station_type/arrival_dist_from_star_ls), not `BioTarget` -- it's
fundamentally "reach a station" (the nearest Vista Genomics), the same
shape mining_sell/mining_start targets already use. §21 defines exactly
two target shapes; this reuses the one that actually fits.
"""
from __future__ import annotations

import math

from sqlalchemy.orm import Session

from app.bio.conditions import (
    USER_UNSCANNED_UNKNOWN_CONFIDENCE,
    detect_unsold_bio_count,
    find_nearby_bio_signal_bodies,
    has_bio_signals,
)
from app.db.models.player import PlayerState
from app.db.models.static import Station, System
from app.scoring.models import BioTarget, DraftCandidate, MiningTarget

DEFAULT_DISTANCE_LIMIT_LY = 200.0  # IMPLEMENTATION_SPEC_V0.2.md §12.1's Input DTO default


def generate_bio_current_body_candidates(session: Session, player_state: PlayerState) -> list[DraftCandidate]:
    if player_state.current_system_address is None or player_state.current_body_id is None:
        return []
    if not has_bio_signals(session, player_state.current_system_address, player_state.current_body_id):
        return []

    target = BioTarget(
        body_name=player_state.current_body_name or "",
        system_name=player_state.current_system or "",
        body_suffix="",
        arrival_dist_from_star_ls=None,
        system_address=player_state.current_system_address,
        body_id=player_state.current_body_id,
    )
    return [
        DraftCandidate(
            action="bio_current_body",
            target=target,
            required_segments=["descent", "bio_sample", "ascent"],  # already at/near the body -- no travel
            generation_confidence=1.0,
        )
    ]


def generate_bio_next_system_candidates(
    session: Session, player_state: PlayerState, distance_limit_ly: float = DEFAULT_DISTANCE_LIMIT_LY
) -> list[DraftCandidate]:
    if player_state.current_system_address is None:
        return []
    origin = session.query(System).filter_by(system_address=player_state.current_system_address).one_or_none()
    if origin is None:
        return []

    candidates: list[DraftCandidate] = []
    for nearby in find_nearby_bio_signal_bodies(session, origin, distance_limit_ly):
        target = BioTarget(
            body_name="",
            system_name=nearby.system.name,
            body_suffix="",
            arrival_dist_from_star_ls=None,
            # The destination body's IDs, not origin's -- Value re-queries
            # BodyBioSignal for this specific candidate body (spec §2).
            system_address=nearby.system.system_address,
            body_id=nearby.body_id,
        )
        candidates.append(
            DraftCandidate(
                action="bio_next_system",
                target=target,
                required_segments=["jump", "supercruise", "descent", "bio_sample", "ascent"],
                # "本人未スキャン" can't be verified either way (design doc §5.2) --
                # never asserted true or false, just flagged as uncertain.
                generation_confidence=USER_UNSCANNED_UNKNOWN_CONFIDENCE,
            )
        )
    return candidates


def generate_bio_return_candidates(session: Session, player_state: PlayerState) -> list[DraftCandidate]:
    if detect_unsold_bio_count(session) <= 0:
        return []
    if player_state.current_system_address is None:
        return []
    origin = session.query(System).filter_by(system_address=player_state.current_system_address).one_or_none()
    if origin is None:
        return []

    nearest_station: Station | None = None
    nearest_system: System | None = None
    nearest_distance: float | None = None
    for station in session.query(Station).filter_by(has_vista_genomics=True).all():
        system = session.query(System).filter_by(system_address=station.system_address).one_or_none()
        if system is None:
            continue
        distance = math.dist((origin.x, origin.y, origin.z), (system.x, system.y, system.z))
        if nearest_distance is None or distance < nearest_distance:
            nearest_distance, nearest_station, nearest_system = distance, station, system

    if nearest_station is None or nearest_system is None:
        return []

    target = MiningTarget(
        station_name=nearest_station.name,
        system_name=nearest_system.name,
        parent_body_name=None,
        station_type=nearest_station.station_type or "",
        arrival_dist_from_star_ls=nearest_station.distance_to_arrival_ls,
    )
    return [
        DraftCandidate(
            action="bio_return",
            target=target,
            required_segments=["jump", "supercruise", "dock"],
            generation_confidence=1.0,
        )
    ]


def generate_bio_candidates(
    session: Session, player_state: PlayerState, distance_limit_ly: float = DEFAULT_DISTANCE_LIMIT_LY
) -> list[DraftCandidate]:
    return (
        generate_bio_current_body_candidates(session, player_state)
        + generate_bio_next_system_candidates(session, player_state, distance_limit_ly)
        + generate_bio_return_candidates(session, player_state)
    )
