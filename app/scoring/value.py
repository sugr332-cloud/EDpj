"""Value / Score calculation — Phase 2-3/2-5C.

Spec (docs/PHASE_2_3_HORIZON_VALUE_DESIGN_BASELINE_V0.1.md §4/§5/§7, v0.4;
docs/PHASE_2_5_CONFIDENCE_EXPLAINABILITY_DESIGN_BASELINE_V0.1.md §7.2, v0.2).

`calculate_value` is attempted for every passed candidate regardless of
horizon completeness (§0/§6) -- it never consults `blocking_segments`.
`mining_start` still always reports a fixed `value_unavailable_reason`
(deliberately out of scope, Phase 2-3 §4.4/§5, not a missing
per-candidate data problem). The three Bio actions now have a value
model (Phase 3 V1, docs/PHASE_3_BIO_VALUE_MODEL_V1_DESIGN_BASELINE_V0.1.md)
-- their `value_unavailable_reason` is per-candidate (no biological
signal count, or no calibration data yet), not a fixed "not implemented"
string.

`calculate_value` returns a `ValueResult` (not a bare tuple) so it can
also report which `MarketLatest.observed_at` values actually contributed
to `expected_value` -- Confidence (app/scoring/confidence.py) needs this
for its freshness factor, and must never re-derive "which market row was
used" independently, since that would duplicate Value's own selection
logic and risk silently diverging from it if that logic ever changes.

`calculate_score`/`is_scoreable`/`calculate_value` are Phase 2-3's whole
responsibility here -- ranking multiple scoreable candidates against each
other (`rank_candidates`/`select_recommendation`/`build_alternatives`) is
explicitly Phase 2-4 (§7) and does not belong in this module.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.bio.conditions import BIOLOGICAL_SIGNAL_TYPE, detect_unsold_bio_count
from app.bio.value import calibrate_expected_value_per_signal
from app.db.models.eddn import BodyBioSignal
from app.db.models.market import MarketLatest
from app.db.models.player import CargoState
from app.mining.cargo_capacity import get_cargo_capacity
from app.mining.price import effective_price
from app.mining.state import MINABLE_COMMODITIES
from app.mining.yield_model import EXPECTED_REFINED_QUANTITY_PER_EVENT
from app.scoring.models import BioTarget, DraftCandidate, MiningTarget

MINING_START_VALUE_UNAVAILABLE_REASON = (
    "not specified by §10.4 (deferred to a future Mining Start Value Model phase)"
)


@dataclass(frozen=True)
class ValueResult:
    """`market_observed_ats` is empty whenever the candidate's value
    didn't depend on any Market observation at all (mining_start/bio_* --
    always `value_unavailable_reason`-only) -- not just when it's
    unavailable for a market-related reason."""

    expected_value: float | None
    value_unavailable_reason: str | None
    market_observed_ats: list[dt.datetime] = field(default_factory=list)


def _mining_sell_value(target: MiningTarget, session: Session) -> ValueResult:
    """§4.2: value = Σ(quantity × effective_price) over held ore that this
    station's market actually buys. Candidate generation already required
    at least one such (commodity, station) match with demand > 0 (see
    app/mining/candidates.py's generate_mining_sell_candidates), so this
    re-derives the same match rather than trusting a cached figure.

    A held commodity's market state at this specific station is one of
    three, and they are NOT interchangeable (edge-case review, Phase 2-3
    follow-up): a `MarketLatest` row with `demand > 0` is a known sale
    (counted); one with `demand == 0` is a *confirmed* "not buying this
    right now" (excluded from the sum, but not "unknown" -- contributing
    0 here is a fact, not a guess); no row at all means we simply haven't
    observed whether this station buys the commodity, which is genuinely
    unknown and must not be silently treated as either "buys it" or
    "doesn't" -- so it blocks the whole candidate's value rather than
    silently under-counting it. `demand < 0` cannot occur from a real
    EDDN/journal observation and is treated the same as "unknown" rather
    than trusted as a confirmed zero."""
    total = 0.0
    observed_ats: list[dt.datetime] = []
    for cargo_row in session.query(CargoState).filter(CargoState.quantity > 0).all():
        if cargo_row.commodity_name not in MINABLE_COMMODITIES:
            continue
        market_row = (
            session.query(MarketLatest)
            .filter_by(station_id=target.station_id, commodity_name=cargo_row.commodity_name)
            .one_or_none()
        )
        if market_row is None or market_row.demand < 0:
            return ValueResult(None, "market_data_incomplete")
        if market_row.demand == 0:
            continue
        total += cargo_row.quantity * effective_price(market_row.sell_price, cargo_row.quantity, market_row.demand)
        observed_ats.append(market_row.observed_at)
    return ValueResult(total, None, observed_ats)


def _mining_continue_value(target: MiningTarget, session: Session) -> ValueResult:
    """§4.3 (v0.4): quantity is the fixed 1t/event constant, commodity is
    whichever `MiningRefined.Type` candidate generation already resolved
    onto the target, cargo capacity comes from the latest `Loadout`
    event, and the sell market is whichever known market for that
    commodity yields the highest §4.1 effective price -- an evaluation
    assumption only, no travel time is added for it."""
    cargo_capacity = get_cargo_capacity(session)
    if cargo_capacity is None:
        return ValueResult(None, "cargo_capacity_unknown")

    market_rows = (
        session.query(MarketLatest)
        .filter(MarketLatest.commodity_name == target.commodity_name, MarketLatest.demand > 0)
        .all()
    )
    if not market_rows:
        return ValueResult(None, "no_market_target")

    current_cargo = sum(row.quantity for row in session.query(CargoState).all())
    evaluation_cargo = min(current_cargo + EXPECTED_REFINED_QUANTITY_PER_EVENT, cargo_capacity)
    best_row = max(market_rows, key=lambda row: effective_price(row.sell_price, evaluation_cargo, row.demand))
    best_effective_price = effective_price(best_row.sell_price, evaluation_cargo, best_row.demand)
    return ValueResult(
        EXPECTED_REFINED_QUANTITY_PER_EVENT * best_effective_price, None, [best_row.observed_at]
    )


def _biological_signal_count(session: Session, system_address: int | None, body_id: int | None) -> int:
    """Re-queries BodyBioSignal by ID rather than trusting anything
    Candidate Generation might have counted (docs/PHASE_3_BIO_VALUE_MODEL_V1...
    §2/§4, same "re-derive, don't trust a cached figure" principle as
    _mining_sell_value). Only BIOLOGICAL_SIGNAL_TYPE rows are summed --
    a body with only geological (or other) signals contributes 0."""
    if system_address is None or body_id is None:
        return 0
    rows = (
        session.query(BodyBioSignal)
        .filter_by(system_address=system_address, body_id=body_id, signal_type=BIOLOGICAL_SIGNAL_TYPE)
        .all()
    )
    return sum(row.count for row in rows)


def _bio_value(target: BioTarget, session: Session) -> ValueResult:
    """bio_current_body/bio_next_system (spec §4): signal_count ×
    calibrate_expected_value_per_signal(). Never fabricates a value when
    either input is missing -- signal_count=0 and "no calibration data
    yet" are reported as distinct value_unavailable_reason strings
    rather than collapsed into one."""
    signal_count = _biological_signal_count(session, target.system_address, target.body_id)
    if signal_count == 0:
        return ValueResult(None, "no_biological_signal_count")
    per_signal = calibrate_expected_value_per_signal(session)
    if per_signal is None:
        return ValueResult(None, "insufficient_sell_history")
    return ValueResult(signal_count * per_signal, None)


def _bio_return_value(session: Session) -> ValueResult:
    """bio_return (spec §4): "value of unsold organic data" (SPECIFICATION_V0.4.md
    §8.7/§11.4), evaluated with the same per-signal calibration as
    _bio_value() -- V1 deliberately does not exploit that bio_return's
    species are actually known (via ScanOrganic's Genus/Species fields),
    keeping all three Bio actions on one unified input source for now
    (spec §9, a V2 candidate)."""
    unsold_count = detect_unsold_bio_count(session)
    if unsold_count == 0:
        return ValueResult(None, "no_unsold_bio_data")
    per_signal = calibrate_expected_value_per_signal(session)
    if per_signal is None:
        return ValueResult(None, "insufficient_sell_history")
    return ValueResult(unsold_count * per_signal, None)


def calculate_value(draft: DraftCandidate, session: Session) -> ValueResult:
    """Exactly one of `expected_value`/`value_unavailable_reason` is None
    on any return, matching IncompleteCandidate's/is_scoreable's
    contract."""
    if draft.action == "mining_sell":
        return _mining_sell_value(draft.target, session)
    if draft.action == "mining_continue":
        return _mining_continue_value(draft.target, session)
    if draft.action == "mining_start":
        return ValueResult(None, MINING_START_VALUE_UNAVAILABLE_REASON)
    if draft.action in ("bio_current_body", "bio_next_system"):
        return _bio_value(draft.target, session)
    return _bio_return_value(session)  # bio_return


def calculate_score(expected_value: float, action_horizon_seconds: float) -> float | None:
    """None if `action_horizon_seconds` isn't a positive duration --
    pipeline.py's `is_scoreable` gate already keeps this from being
    called in that state, but this stays defensive on its own (a
    calibrated segment landing on a 0.0-second median, however unlikely,
    must never turn into a division by zero / infinite score)."""
    if action_horizon_seconds <= 0:
        return None
    return expected_value / (action_horizon_seconds / 3600)
