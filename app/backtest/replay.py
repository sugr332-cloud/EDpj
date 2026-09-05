"""Historical Replay primitives — Phase 2-6A.

Spec (docs/PHASE_2_6A_HISTORICAL_REPLAY_IMPLEMENTATION_BASELINE_V0.1.md,
v0.2). Builds the T0-bounded market-state primitive that Phase 2-6B
(volatility threshold evaluation) and 2-6C (freshness curve evaluation)
consume directly to measure forecast error against real EDDN archive
data. This module does NOT wire the full Candidate Generation -> Ranking
pipeline (§1 of the spec) -- CargoState/PlayerState/Loadout are not
present anywhere in the EDDN archive; that wiring is Phase 2-6D's job,
against the real Journal, reusing only the MarketLatest-shaped
reconstruction this module's T0 boundary makes possible.

`PredictionInput` (observed_at <= t0) and `ActualObservation`
(t0 < observed_at) are separate types, built by separate query
functions, so a forecast-error computation can never accidentally
mix which side is "known at T0" and which side is "the future"
(spec §4.4) -- this replaces v0.1's design, which reused
`price_change_ratio`'s bare (prev, curr) pair directly as the error,
conflating "predicted value" and "actual value" into one anonymous
calculation (reviewer feedback that produced the v0.2 baseline).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models.market import MarketHistoricalObservation
from app.market.predictability import (
    MAX_OBSERVATION_GAP,
    VolatilityClass,
    VolatilityComputation,
    _compute_volatility_stats,
)
from app.scoring.confidence import FRESHNESS_FLOOR_THRESHOLD, FRESHNESS_FULL_THRESHOLD

# Shared with app/scoring/confidence.py's freshness curve breakpoints
# (spec §4.5) so 2-6B (volatility class vs. forecast error) and 2-6C
# (freshness curve shape) measure "age -> price deviation" on the same
# basis rather than inventing separate horizons.
DEFAULT_REPLAY_HORIZONS: list[dt.timedelta] = [
    FRESHNESS_FULL_THRESHOLD,  # 15 minutes
    dt.timedelta(hours=1),
    dt.timedelta(hours=6),
    FRESHNESS_FLOOR_THRESHOLD,  # 24 hours
]


def _naive(ts: dt.datetime) -> dt.datetime:
    # SQLite's DateTime(timezone=True) doesn't round-trip tzinfo -- a row
    # read back from MarketHistoricalObservation.observed_at comes back
    # naive even though it was written as UTC-aware. Same workaround used
    # throughout this project (e.g. app/scoring/confidence.py's
    # market_freshness, app/mining/state.py's _find_recent_mining_refined).
    return ts.replace(tzinfo=None) if ts.tzinfo is not None else ts


@dataclass(frozen=True)
class PredictionInput:
    """Everything the naive persistence forecast knows at T0. Built only
    from `observed_at <= t0` rows -- never touches anything after t0
    (spec §4.1/§4.4)."""

    t0: dt.datetime
    predicted_price: float
    predicted_price_observed_at: dt.datetime
    volatility_class: VolatilityClass
    sample_count_at_t0: int


@dataclass(frozen=True)
class ActualObservation:
    """What actually happened after T0. Built only from
    `observed_at > t0` rows -- a backtest-evaluator-only view that must
    never feed back into PredictionInput (spec §4.2/§4.4)."""

    observed_at: dt.datetime
    actual_price: float


@dataclass(frozen=True)
class ReplaySample:
    prediction: PredictionInput
    actual: ActualObservation | None  # None when observe_actual_after() found nothing in range
    horizon: dt.timedelta
    forecast_error: float | None  # None whenever `actual` is None, or predicted_price <= 0 -- never 0/interpolated


def predict_naive_persistence(
    session: Session,
    station_id: int,
    commodity_name: str,
    t0: dt.datetime,
    window_days: int,
) -> PredictionInput | None:
    """The naive persistence forecast: "the price stays at whatever it
    last was observed to be at T0". `volatility_class`/`sample_count_at_t0`
    come from `_compute_volatility_stats` over the same window ending at
    t0 -- the exact classification logic under evaluation by Phase 2-6B,
    not a re-derived approximation of it. Returns None if there is no
    observation at or before t0 to predict from."""
    latest = (
        session.query(MarketHistoricalObservation)
        .filter_by(station_id=station_id, commodity_name=commodity_name)
        .filter(MarketHistoricalObservation.observed_at <= t0)
        .order_by(MarketHistoricalObservation.observed_at.desc())
        .first()
    )
    if latest is None:
        return None

    window_start = t0 - dt.timedelta(days=window_days)
    computation: VolatilityComputation = _compute_volatility_stats(
        session, station_id, commodity_name, window_start, t0
    )
    return PredictionInput(
        t0=t0,
        predicted_price=float(latest.sell_price),
        predicted_price_observed_at=latest.observed_at,
        volatility_class=computation.volatility_class,
        sample_count_at_t0=computation.sample_count,
    )


def observe_actual_after(
    session: Session,
    station_id: int,
    commodity_name: str,
    t0: dt.datetime,
    horizon: dt.timedelta,
    max_gap: dt.timedelta = MAX_OBSERVATION_GAP,
) -> ActualObservation | None:
    """The observation nearest to `t0 + horizon`, searched only within
    `(t0, t0 + horizon + max_gap]`. A missing period is never
    interpolated (docs/MARKET_PREDICTABILITY_SPEC_V0.1.md §4.1) -- if
    nothing falls in range, this returns None rather than guessing."""
    target = t0 + horizon
    window_end = target + max_gap
    candidates = (
        session.query(MarketHistoricalObservation)
        .filter_by(station_id=station_id, commodity_name=commodity_name)
        .filter(MarketHistoricalObservation.observed_at > t0)
        .filter(MarketHistoricalObservation.observed_at <= window_end)
        .all()
    )
    if not candidates:
        return None
    naive_target = _naive(target)
    nearest = min(candidates, key=lambda row: abs(_naive(row.observed_at) - naive_target))
    return ActualObservation(observed_at=nearest.observed_at, actual_price=float(nearest.sell_price))


def evaluate_forecast_at(
    session: Session,
    station_id: int,
    commodity_name: str,
    t0: dt.datetime,
    window_days: int,
    horizon: dt.timedelta,
) -> ReplaySample | None:
    """Composes PredictionInput and ActualObservation into one sample.
    Returns None only when there's nothing to predict from at all
    (no observation at or before t0) -- a missing *actual* observation
    still produces a ReplaySample, just with `forecast_error=None`
    (spec §4.3), so callers can distinguish "no data to evaluate" from
    "prediction existed but nothing to compare it against"."""
    prediction = predict_naive_persistence(session, station_id, commodity_name, t0, window_days)
    if prediction is None:
        return None

    actual = observe_actual_after(session, station_id, commodity_name, t0, horizon)
    forecast_error = None
    if actual is not None and prediction.predicted_price > 0:
        forecast_error = abs(actual.actual_price - prediction.predicted_price) / prediction.predicted_price

    return ReplaySample(prediction=prediction, actual=actual, horizon=horizon, forecast_error=forecast_error)


def compare_windows(
    session: Session,
    station_id: int,
    commodity_name: str,
    now: dt.datetime,
    window_days_options: tuple[int, ...] = (7, 14, 30),
) -> dict[int, VolatilityComputation]:
    """Independent per-window_days classification for the same T0
    (`now`), without ever calling `analyze_market()` or writing to
    `MarketPredictability` -- that table's unique constraint is
    `(station_id, commodity_name, window_end)`, which does not include
    `window_days`, so three `analyze_market()` calls at the same `now`
    would silently overwrite each other's result
    (docs/PHASE_2_6A_HISTORICAL_REPLAY_IMPLEMENTATION_BASELINE_V0.1.md
    §3.1). This function only reads `MarketHistoricalObservation` that
    the caller has already ensured is cached (e.g. via
    `app.market.predictability.ensure_days_fetched`) -- it does not fetch
    from the archive itself."""
    return {
        window_days: _compute_volatility_stats(
            session, station_id, commodity_name, now - dt.timedelta(days=window_days), now
        )
        for window_days in window_days_options
    }
