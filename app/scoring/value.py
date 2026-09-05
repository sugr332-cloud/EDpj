"""Value / Score calculation — Phase 2-3.

Spec (docs/PHASE_2_3_HORIZON_VALUE_DESIGN_BASELINE_V0.1.md §4/§5/§7, v0.4).

`calculate_value` is attempted for every passed candidate regardless of
horizon completeness (§0/§6) -- it never consults `blocking_segments`.
Only `mining_sell`/`mining_continue` can currently return a value;
`mining_start` and all three Bio actions always report a fixed
`value_unavailable_reason` because their respective value models are
deliberately out of scope for Phase 2-3 (§4.4/§5), not because of any
missing per-candidate data.

`calculate_score`/`is_scoreable`/`calculate_value` are Phase 2-3's whole
responsibility here -- ranking multiple scoreable candidates against each
other (`rank_candidates`/`select_recommendation`/`build_alternatives`) is
explicitly Phase 2-4 (§7) and does not belong in this module.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models.market import MarketLatest
from app.db.models.player import CargoState
from app.mining.cargo_capacity import get_cargo_capacity
from app.mining.price import effective_price
from app.mining.state import MINABLE_COMMODITIES
from app.mining.yield_model import EXPECTED_REFINED_QUANTITY_PER_EVENT
from app.scoring.models import DraftCandidate, MiningTarget

MINING_START_VALUE_UNAVAILABLE_REASON = (
    "not specified by §10.4 (deferred to a future Mining Start Value Model phase)"
)
BIO_VALUE_UNAVAILABLE_REASON = "species value model not implemented"


def _mining_sell_value(target: MiningTarget, session: Session) -> tuple[float | None, str | None]:
    """§4.2: value = Σ(quantity × effective_price) over held ore that this
    station's market actually buys. Candidate generation already required
    at least one such (commodity, station) match with demand > 0 (see
    app/mining/candidates.py's generate_mining_sell_candidates), so this
    re-derives the same match rather than trusting a cached figure."""
    total = 0.0
    for cargo_row in session.query(CargoState).filter(CargoState.quantity > 0).all():
        if cargo_row.commodity_name not in MINABLE_COMMODITIES:
            continue
        market_row = (
            session.query(MarketLatest)
            .filter_by(station_id=target.station_id, commodity_name=cargo_row.commodity_name)
            .one_or_none()
        )
        if market_row is None or market_row.demand <= 0:
            continue
        total += cargo_row.quantity * effective_price(market_row.sell_price, cargo_row.quantity, market_row.demand)
    return total, None


def _mining_continue_value(target: MiningTarget, session: Session) -> tuple[float | None, str | None]:
    """§4.3 (v0.4): quantity is the fixed 1t/event constant, commodity is
    whichever `MiningRefined.Type` candidate generation already resolved
    onto the target, cargo capacity comes from the latest `Loadout`
    event, and the sell market is whichever known market for that
    commodity yields the highest §4.1 effective price -- an evaluation
    assumption only, no travel time is added for it."""
    cargo_capacity = get_cargo_capacity(session)
    if cargo_capacity is None:
        return None, "cargo_capacity_unknown"

    market_rows = (
        session.query(MarketLatest)
        .filter(MarketLatest.commodity_name == target.commodity_name, MarketLatest.demand > 0)
        .all()
    )
    if not market_rows:
        return None, "no_market_target"

    current_cargo = sum(row.quantity for row in session.query(CargoState).all())
    evaluation_cargo = min(current_cargo + EXPECTED_REFINED_QUANTITY_PER_EVENT, cargo_capacity)
    best_effective_price = max(
        effective_price(row.sell_price, evaluation_cargo, row.demand) for row in market_rows
    )
    return EXPECTED_REFINED_QUANTITY_PER_EVENT * best_effective_price, None


def calculate_value(draft: DraftCandidate, session: Session) -> tuple[float | None, str | None]:
    """Returns (expected_value, value_unavailable_reason) -- exactly one
    of the two is None on any return, matching IncompleteCandidate's/
    is_scoreable's contract."""
    if draft.action == "mining_sell":
        return _mining_sell_value(draft.target, session)
    if draft.action == "mining_continue":
        return _mining_continue_value(draft.target, session)
    if draft.action == "mining_start":
        return None, MINING_START_VALUE_UNAVAILABLE_REASON
    return None, BIO_VALUE_UNAVAILABLE_REASON  # bio_current_body / bio_next_system / bio_return


def calculate_score(expected_value: float, action_horizon_seconds: float) -> float:
    return expected_value / (action_horizon_seconds / 3600)
