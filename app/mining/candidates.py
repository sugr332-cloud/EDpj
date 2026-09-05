"""Mining candidate generation — Phase 2-2.

Spec (IMPLEMENTATION_SPEC_V0.2.md §8.3, docs/PHASE_2_2_CANDIDATE_GENERATION_DESIGN_BASELINE_V0.1.md §4).

Per design doc §1.1: candidates requiring `supercruise` (mining_sell,
mining_start) are generated regardless of the fact that `supercruise` is
currently `unavailable` — that's Horizon's problem to surface as
`IncompleteCandidate`, not something this module checks or reacts to.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models.market import MarketLatest
from app.db.models.static import Station, System
from app.mining.state import MiningContext, detect_mining_context, find_historical_ring_locations
from app.scoring.models import DraftCandidate, MiningTarget


def _pad_label(landing_pad: dict | None) -> str | None:
    if not landing_pad:
        return None
    for size in ("large", "medium", "small"):
        if landing_pad.get(size, 0) > 0:
            return size
    return None


def _system_name(session: Session, system_address: int | None) -> str:
    if system_address is None:
        return ""
    system = session.query(System).filter_by(system_address=system_address).one_or_none()
    return system.name if system is not None else ""


def generate_mining_sell_candidates(session: Session, context: MiningContext) -> list[DraftCandidate]:
    """IMPLEMENTATION_SPEC_V0.2.md §7.1: `mining_sell` does not require
    `mining_active` -- ore cargo alone is enough (§16 regression
    requirement, carried into design doc §4.3)."""
    if not context.has_mining_cargo:
        return []

    commodity_names = [name for name, _qty in context.ore_cargo]
    rows = (
        session.query(MarketLatest)
        .filter(MarketLatest.commodity_name.in_(commodity_names), MarketLatest.demand > 0)
        .all()
    )

    by_station: dict[int, list[MarketLatest]] = {}
    for row in rows:
        by_station.setdefault(row.station_id, []).append(row)

    candidates: list[DraftCandidate] = []
    for station_id in by_station:
        station = session.query(Station).filter_by(station_id=station_id).one_or_none()
        if station is None:
            # Not yet resolved via Spansh (Phase 1's on-demand policy) --
            # no identity to build a candidate from. Documented gap, not
            # silently guessed; this station will produce a candidate
            # once it's been looked up.
            continue

        target = MiningTarget(
            station_name=station.name,
            system_name=_system_name(session, station.system_address),
            parent_body_name=None,
            station_type=station.station_type or "",
            arrival_dist_from_star_ls=station.distance_to_arrival_ls,
            max_landing_pad=_pad_label(station.landing_pad),
            station_id=station.station_id,
        )
        candidates.append(
            DraftCandidate(
                action="mining_sell",
                target=target,
                required_segments=["jump", "supercruise", "dock"],
                generation_confidence=context.generation_confidence,
            )
        )
    return candidates


def generate_mining_continue_candidates(session: Session, context: MiningContext) -> list[DraftCandidate]:
    if not context.mining_active:
        return []

    target = MiningTarget(
        station_name="",
        system_name=_system_name(session, context.last_ring_system_address),
        parent_body_name=None,
        station_type="ring",
        arrival_dist_from_star_ls=None,
        commodity_name=context.last_refined_commodity,
    )
    return [
        DraftCandidate(
            action="mining_continue",
            target=target,
            required_segments=["mining_cycle"],
            generation_confidence=context.generation_confidence,
        )
    ]


def generate_mining_start_candidates(session: Session, context: MiningContext) -> list[DraftCandidate]:
    """Ring candidates come only from the player's own MiningRefined
    history (design doc §4.4, priority 1). Priority 2 (guessing from
    Body.body_type/sub_type) is not implemented -- verified against the
    live Spansh system-dump response, body records carry nothing that
    indicates ring presence (see app/mining/state.py's
    find_historical_ring_locations docstring). With no history, this
    generates no candidates at all."""
    if context.has_mining_cargo:
        return []

    candidates: list[DraftCandidate] = []
    for location in find_historical_ring_locations(session):
        target = MiningTarget(
            station_name="",
            system_name=_system_name(session, location.system_address),
            parent_body_name=None,
            station_type="ring",
            arrival_dist_from_star_ls=None,
        )
        candidates.append(
            DraftCandidate(
                action="mining_start",
                target=target,
                required_segments=["jump", "supercruise", "mining_cycle"],
                generation_confidence=1.0,  # real observed history, not a guess
            )
        )
    return candidates


def generate_mining_candidates(session: Session, context: MiningContext | None = None) -> list[DraftCandidate]:
    context = context if context is not None else detect_mining_context(session)
    return (
        generate_mining_sell_candidates(session, context)
        + generate_mining_continue_candidates(session, context)
        + generate_mining_start_candidates(session, context)
    )
