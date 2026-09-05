"""Mining Sell Formula Validation — Phase 2-6F-1.

Spec (docs/PHASE_2_6F_FORMULA_VALIDATION_GATE_DESIGN_BASELINE_V0.1.md §3).
Evaluation cases are real `MarketSell` journal events -- the moment the
player actually sold, not a hypothetical timing -- so there is no
arbitrary choice of T0. For each such event:

  predicted_value = the T0-bound backtest formula (§below), using
                     `reconstruct_cargo_at_t0` for held cargo and
                     `MarketHistoricalObservation` for the T0-bound
                     market price/demand -- never the live
                     `CargoState`/`MarketLatest` tables `_mining_sell_value`
                     (app/scoring/value.py) itself queries.
  actual_value    = read directly off the MarketSell event's own
                     payload -- an already-known outcome, not a forecast
                     that needs a separate future observation.

A case is excluded (and separately counted, never silently dropped)
when `reconstruct_cargo_at_t0` returns None (no Cargo checkpoint before
this sell) or when a held MINABLE_COMMODITIES row has no
MarketHistoricalObservation at or before T0 for this station -- both
are "cannot compute predicted_value", not "predicted_value is 0".
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.backtest.cargo_reconstruction import CargoReconstructionIntegrityError, reconstruct_cargo_at_t0
from app.backtest.formula_validation import EvaluationCase, FormulaAccuracyResult, compute_formula_accuracy
from app.db.models.journal import JournalEvent
from app.db.models.market import MarketHistoricalObservation
from app.journal.extractor import strip_internal_name
from app.mining.price import effective_price
from app.mining.state import MINABLE_COMMODITIES

MARKET_SELL_EVENT = "MarketSell"

# Matches volatility_evaluation.py's MIN_SAMPLES_FOR_EVALUATION precedent
# (app/backtest/volatility_evaluation.py) -- not derived from this
# player's real distribution yet (there are 0 real MarketSell events as
# of 2026-09-06), so this is a placeholder consistent with the rest of
# the project's minimum-sample conventions, to be revisited once real
# data exists (ABSOLUTE_FORMULA_VALIDATION_GATE_V0.1.md §6: never lower
# it just to manufacture a PASS -- also never raise/lower it based on
# vibes once real data starts arriving without re-justifying the choice).
MINIMUM_MINING_SELL_CASES = 30

# The exact instant of the sell event itself must not be included in its
# own "held cargo at T0" reconstruction (that would already reflect the
# sale having happened) -- back off by the smallest meaningful step so
# `reconstruct_cargo_at_t0`'s `<= t0` bound lands strictly before it.
_JUST_BEFORE = dt.timedelta(microseconds=1)


@dataclass(frozen=True)
class ExclusionCounts:
    no_cargo_checkpoint: int = 0
    no_market_data: int = 0
    integrity_error: int = 0


@dataclass(frozen=True)
class MiningSellCaseCollection:
    cases: list[EvaluationCase]
    total_sell_events: int
    excluded: ExclusionCounts


def _actual_value_from_sell_event(event: JournalEvent) -> float:
    payload = event.payload
    if "TotalSale" in payload:
        return float(payload["TotalSale"])
    return float(payload["Count"]) * float(payload["SellPrice"])


def _market_row_at_or_before(
    session: Session, station_id: int, commodity_name: str, t0: dt.datetime
) -> MarketHistoricalObservation | None:
    return (
        session.query(MarketHistoricalObservation)
        .filter_by(station_id=station_id, commodity_name=commodity_name)
        .filter(MarketHistoricalObservation.observed_at <= t0)
        .order_by(MarketHistoricalObservation.observed_at.desc())
        .first()
    )


def _backtest_predicted_value(
    session: Session, station_id: int, cargo_at_t0: dict[str, int], t0: dt.datetime
) -> float | None:
    """T0-bound reimplementation of `_mining_sell_value`'s per-commodity
    sum (app/scoring/value.py) -- same MINABLE_COMMODITIES/effective_price
    logic, but reading cargo from an explicit dict and market price from
    `MarketHistoricalObservation` instead of querying the live
    `CargoState`/`MarketLatest` tables directly (§1 of the design doc:
    this formula must never touch live CargoState)."""
    total = 0.0
    for commodity_name, quantity in cargo_at_t0.items():
        if commodity_name not in MINABLE_COMMODITIES or quantity <= 0:
            continue
        market_row = _market_row_at_or_before(session, station_id, commodity_name, t0)
        if market_row is None:
            return None
        total += quantity * effective_price(market_row.sell_price, quantity, market_row.demand)
    return total


def collect_mining_sell_evaluation_cases(session: Session) -> MiningSellCaseCollection:
    sell_events = session.query(JournalEvent).filter_by(event_type=MARKET_SELL_EVENT).order_by(JournalEvent.timestamp.asc()).all()

    cases: list[EvaluationCase] = []
    no_cargo_checkpoint = 0
    no_market_data = 0
    integrity_error = 0

    for event in sell_events:
        t0_before = event.timestamp - _JUST_BEFORE
        try:
            cargo_at_t0 = reconstruct_cargo_at_t0(session, t0_before)
        except CargoReconstructionIntegrityError:
            integrity_error += 1
            continue
        if cargo_at_t0 is None:
            no_cargo_checkpoint += 1
            continue

        station_id = event.payload["MarketID"]
        predicted_value = _backtest_predicted_value(session, station_id, cargo_at_t0, t0_before)
        if predicted_value is None:
            no_market_data += 1
            continue

        cases.append(EvaluationCase(predicted_value=predicted_value, actual_value=_actual_value_from_sell_event(event)))

    return MiningSellCaseCollection(
        cases=cases,
        total_sell_events=len(sell_events),
        excluded=ExclusionCounts(
            no_cargo_checkpoint=no_cargo_checkpoint, no_market_data=no_market_data, integrity_error=integrity_error
        ),
    )


def evaluate_mining_sell_formula(session: Session, minimum_cases: int) -> tuple[FormulaAccuracyResult, MiningSellCaseCollection]:
    collection = collect_mining_sell_evaluation_cases(session)
    return compute_formula_accuracy(collection.cases, minimum_cases), collection
