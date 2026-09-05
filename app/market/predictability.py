"""Market predictability orchestration — Phase 2-5A.

Spec (docs/PHASE_2_5A_MARKET_PREDICTABILITY_IMPLEMENTATION_BASELINE_V0.1.md
§7/§9/§10). Fetches (on-demand, via the narrow cache below) -> pairs ->
computes volatility -> classifies -> persists one MarketPredictability
row per (station_id, commodity_name) analysis run.

Every numeric threshold in this module is an explicit placeholder --
docs/MARKET_PREDICTABILITY_SPEC_V0.1.md §8 requires classification
boundaries to come from real data + backtest results (Phase 2-6), not be
guessed up front. These constants only exist so the classifier itself is
testable; they are not the final calibrated values.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from app.collectors.eddn import MalformedEddnMessage, parse_commodity_message
from app.collectors.eddn_archive import StreamingHttpClient, iter_commodity_day
from app.db.models.market import MarketHistoricalFetchLog, MarketHistoricalObservation, MarketPredictability
from app.db.upsert import upsert_ignore, upsert_preserve_columns
from app.market.volatility import Observation, demand_change_ratio, median_and_p95, pair_observations, price_change_ratio

# Operational default -- NOT a statistically optimal window. Phase 2-6's
# historical replay compares 7/14/30-day windows against actual forecast
# error before any of these become "the right" value.
DEFAULT_ANALYSIS_WINDOW_DAYS = 14

MAX_OBSERVATION_GAP = dt.timedelta(hours=6)
DEMAND_FLOOR = 1
MIN_SAMPLES_FOR_CLASSIFICATION = 10
STABLE_MEDIAN_PRICE_CHANGE = 0.05
MODERATE_MEDIAN_PRICE_CHANGE = 0.15
MODEL_VERSION = "2-5a-v1"

VolatilityClass = Literal["STABLE", "MODERATE", "VOLATILE", "INSUFFICIENT"]


def classify(sample_count: int, median_abs_price_change: float | None) -> VolatilityClass:
    """Price volatility only (docs/PHASE_2_5A... §7/§10 decision 3) --
    demand volatility is diagnostic, never folded into this."""
    if sample_count < MIN_SAMPLES_FOR_CLASSIFICATION or median_abs_price_change is None:
        return "INSUFFICIENT"
    if median_abs_price_change < STABLE_MEDIAN_PRICE_CHANGE:
        return "STABLE"
    if median_abs_price_change < MODERATE_MEDIAN_PRICE_CHANGE:
        return "MODERATE"
    return "VOLATILE"


def ensure_days_fetched(
    session: Session,
    station_id: int,
    commodity_name: str,
    dates: list[dt.date],
    client: StreamingHttpClient,
) -> None:
    """Single-target convenience wrapper around ensure_days_fetched_batch()
    -- kept for existing single-target callers (analyze_market()). Prefer
    ensure_days_fetched_batch() when multiple (station_id, commodity_name)
    targets need the same date range: calling this in a loop re-downloads
    and re-streams each date's archive file once per target, which Phase
    2-6E's real-data pilot found costing 35 downloads for 5 same-station
    targets over a 7-day window where 7 would do (docs/PHASE_2_6E...v0.2
    §14)."""
    ensure_days_fetched_batch(session, [(station_id, commodity_name)], dates, client)


def ensure_days_fetched_batch(
    session: Session,
    targets: list[tuple[int, str]],
    dates: list[dt.date],
    client: StreamingHttpClient,
) -> None:
    """Like ensure_days_fetched(), but for multiple (station_id,
    commodity_name) targets at once. For each date, downloads and
    streams that date's archive file AT MOST ONCE, extracting rows for
    every target still missing from MarketHistoricalFetchLog in that
    same pass -- rather than once per target (docs/PHASE_2_6E...v0.2
    §14: real Model Validation data found 5 targets at the same station
    triggering 35 redundant downloads of the same 7 days).

    MarketHistoricalFetchLog's granularity is deliberately UNCHANGED
    (station_id, commodity_name, date), not collapsed to date-only: a
    target added in a later, separate call must still be correctly
    (re-)scanned even if the date was already covered for other targets
    in an earlier call -- collapsing the key would silently make a
    genuinely new target look "already fetched" for a date it was never
    actually extracted for. The efficiency gain comes entirely from
    batching *within* one call across the full target list the caller
    already knows about, not from weakening the cache key."""
    for date in dates:
        already_fetched = {
            (row.station_id, row.commodity_name)
            for row in session.query(MarketHistoricalFetchLog.station_id, MarketHistoricalFetchLog.commodity_name)
            .filter_by(date=date)
            .all()
        }
        missing = [target for target in targets if target not in already_fetched]
        if not missing:
            continue

        missing_set = set(missing)
        missing_station_ids = {station_id for station_id, _ in missing}
        matches_by_target: dict[tuple[int, str], list[dict]] = {target: [] for target in missing}
        for envelope in iter_commodity_day(date, client):
            message = envelope.get("message")
            if not isinstance(message, dict) or message.get("marketId") not in missing_station_ids:
                continue
            try:
                rows = parse_commodity_message(message, received_at=dt.datetime.now(dt.timezone.utc))
            except MalformedEddnMessage:
                continue
            for row in rows:
                key = (row["station_id"], row["commodity_name"])
                if key in missing_set:
                    matches_by_target[key].append(row)

        for target in missing:
            station_id, commodity_name = target
            observation_rows = [
                {
                    "station_id": row["station_id"],
                    "commodity_name": row["commodity_name"],
                    "sell_price": row["sell_price"],
                    "demand": row["demand"],
                    "observed_at": row["observed_at"],
                }
                for row in matches_by_target[target]
            ]
            upsert_ignore(
                session, MarketHistoricalObservation, observation_rows, ["station_id", "commodity_name", "observed_at"]
            )
            session.add(
                MarketHistoricalFetchLog(
                    station_id=station_id, commodity_name=commodity_name, date=date,
                    fetched_at=dt.datetime.now(dt.timezone.utc),
                )
            )
        session.commit()


@dataclass(frozen=True)
class VolatilityComputation:
    """The computed part of a MarketPredictability row, without any of
    the identity/bookkeeping columns (station_id, commodity_name,
    window_start, window_end, model_version, computed_at) -- those are
    caller concerns (who is asking, for which window), not part of the
    statistics themselves. Read-only: producing this never writes to the
    database (docs/PHASE_2_6A_HISTORICAL_REPLAY_IMPLEMENTATION_BASELINE_V0.1.md
    §2.1) -- both `analyze_market` (persists) and
    `app.backtest.replay.compare_windows` (does not) build on top of it."""

    sample_count: int
    median_abs_price_change: float | None
    p95_abs_price_change: float | None
    median_abs_demand_change: float | None
    p95_abs_demand_change: float | None
    median_observation_gap_seconds: float | None
    p95_observation_gap_seconds: float | None
    volatility_class: VolatilityClass


def _compute_volatility_stats(
    session: Session, station_id: int, commodity_name: str, window_start: dt.datetime, now: dt.datetime
) -> VolatilityComputation:
    """Reads whatever MarketHistoricalObservation rows are already cached
    in `[window_start, now]` and computes volatility/gap statistics --
    does not fetch anything itself (the caller decides whether/how to
    ensure the window is cached first, e.g. via `ensure_days_fetched`)."""
    rows = (
        session.query(MarketHistoricalObservation)
        .filter_by(station_id=station_id, commodity_name=commodity_name)
        .filter(MarketHistoricalObservation.observed_at >= window_start)
        .filter(MarketHistoricalObservation.observed_at <= now)
        .order_by(MarketHistoricalObservation.observed_at.asc())
        .all()
    )
    observations = [Observation(observed_at=r.observed_at, price=r.sell_price, demand=r.demand) for r in rows]

    volatility_pairs, all_gaps = pair_observations(observations, MAX_OBSERVATION_GAP)

    price_changes = []
    demand_changes = []
    for prev, curr in volatility_pairs:
        ratio = price_change_ratio(prev, curr)
        if ratio is not None:
            price_changes.append(ratio)
        demand_changes.append(demand_change_ratio(prev, curr, DEMAND_FLOOR))

    median_price, p95_price = median_and_p95(price_changes)
    median_demand, p95_demand = median_and_p95(demand_changes)
    gap_seconds = [gap.total_seconds() for gap in all_gaps]
    median_gap, p95_gap = median_and_p95(gap_seconds)

    return VolatilityComputation(
        sample_count=len(observations),
        median_abs_price_change=median_price,
        p95_abs_price_change=p95_price,
        median_abs_demand_change=median_demand,
        p95_abs_demand_change=p95_demand,
        median_observation_gap_seconds=median_gap,
        p95_observation_gap_seconds=p95_gap,
        volatility_class=classify(len(observations), median_price),
    )


def analyze_market(
    session: Session,
    station_id: int,
    commodity_name: str,
    client: StreamingHttpClient,
    window_days: int = DEFAULT_ANALYSIS_WINDOW_DAYS,
    now: dt.datetime | None = None,
) -> MarketPredictability:
    """Ensures the analysis window is cached locally (fetching only
    missing days from the archive), then computes volatility/gap
    statistics and persists one MarketPredictability row. Does not decide
    whether/how a caller uses `volatility_class` -- that wiring into
    Value calculation is Phase 2-5B/C (§0)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    window_start = now - dt.timedelta(days=window_days)

    dates = [
        (window_start + dt.timedelta(days=offset)).date()
        for offset in range((now.date() - window_start.date()).days + 1)
    ]
    ensure_days_fetched(session, station_id, commodity_name, dates, client)

    computation = _compute_volatility_stats(session, station_id, commodity_name, window_start, now)

    # Upsert, not insert: docs/PHASE_2_5A... §3 treats this as a
    # re-computable derived result, not an append-only log -- re-running
    # analyze_market for the same (station_id, commodity_name, window_end)
    # (e.g. `now` passed explicitly, or two calls within the same second)
    # must overwrite, not collide with the unique constraint. Same
    # "preserve_columns=set()" pattern app/calibration/engine.py uses for
    # CalibrationModel.
    upsert_preserve_columns(
        session,
        MarketPredictability,
        [
            {
                "station_id": station_id,
                "commodity_name": commodity_name,
                "sample_count": computation.sample_count,
                "window_start": window_start,
                "window_end": now,
                "median_abs_price_change": computation.median_abs_price_change,
                "p95_abs_price_change": computation.p95_abs_price_change,
                "median_abs_demand_change": computation.median_abs_demand_change,
                "p95_abs_demand_change": computation.p95_abs_demand_change,
                "median_observation_gap_seconds": computation.median_observation_gap_seconds,
                "p95_observation_gap_seconds": computation.p95_observation_gap_seconds,
                "volatility_class": computation.volatility_class,
                "model_version": MODEL_VERSION,
                "computed_at": now,
            }
        ],
        ["station_id", "commodity_name", "window_end"],
        preserve_columns=set(),
    )
    session.commit()
    return (
        session.query(MarketPredictability)
        .filter_by(station_id=station_id, commodity_name=commodity_name, window_end=now)
        .one()
    )


def get_predictability(session: Session, station_id: int, commodity_name: str) -> MarketPredictability | None:
    """The most recently computed row, or None if this (station_id,
    commodity_name) has never been analyzed -- distinct from
    volatility_class="INSUFFICIENT" (analyzed, but too few samples)."""
    return (
        session.query(MarketPredictability)
        .filter_by(station_id=station_id, commodity_name=commodity_name)
        .order_by(MarketPredictability.computed_at.desc())
        .first()
    )
