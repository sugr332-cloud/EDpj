"""Volatility metric selection & threshold sensitivity — Phase 2-6B v0.2.

Spec (docs/PHASE_2_6B_VOLATILITY_EVALUATION_IMPLEMENTATION_BASELINE_V0.1.md
v0.2, §16). Real 20-target/7-day Model Validation data
(docs/PHASE_2_6E_FINAL_EVALUATION_IMPLEMENTATION_BASELINE_V0.1.md §15)
found `median_abs_price_change` (the current production classify()
statistic) structurally saturates at exactly 0 whenever more than half
of adjacent observation pairs show no price change at all -- true for
16/20 of that run's targets. A per-target Spearman correlation against
forecast_error (N=20) showed median_abs_price_change correlating
moderately (0.806) while p95_abs_price_change/nonzero_change_ratio/
max_abs_price_change correlated far more strongly (0.90-0.94), and raw
sample count (pair_n) showed essentially no correlation (-0.126) --
ruling out "more data just looks more volatile" as a confound.

This module is completely independent of app.market.predictability's
production classify()/STABLE_MEDIAN_PRICE_CHANGE/
MODERATE_MEDIAN_PRICE_CHANGE/MarketPredictability -- it never reads or
writes any of them. Nothing here decides which metric/threshold to
adopt: sweep_metric_thresholds() returns facts (class distributions,
ordering hypothesis results) for a human to review under
docs/PHASE_2_6E_FINAL_EVALUATION_IMPLEMENTATION_BASELINE_V0.1.md §7's
adoption procedure, exactly as 2-6B's existing
evaluate_ordering_hypothesis() already does for the production metric.
"""
from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.backtest.replay import ReplaySample, collect_replay_samples
from app.backtest.volatility_evaluation import ClassForecastErrorStats, OrderingHypothesisResult, evaluate_ordering_hypothesis
from app.db.models.market import MarketHistoricalObservation
from app.market.predictability import MAX_OBSERVATION_GAP, MIN_SAMPLES_FOR_CLASSIFICATION, VolatilityClass
from app.market.volatility import Observation, median_and_p95, pair_observations, price_change_ratio

CANDIDATE_METRICS = (
    "median_abs_price_change",  # current production statistic, kept for comparison
    "p95_abs_price_change",  # primary candidate -- robust to a single outlier, avoids median's zero-saturation
    "nonzero_change_ratio",  # secondary candidate (activity, not magnitude) -- kept as a separate feature
    "max_abs_price_change",  # diagnostic only -- sensitive to a single extreme observation
)

# Operational default for sweep_metric_thresholds() -- STABLE:MODERATE
# kept at the same 1:3 ratio as the current production thresholds
# (STABLE_MEDIAN_PRICE_CHANGE=0.05, MODERATE_MEDIAN_PRICE_CHANGE=0.15),
# not a statistically derived value.
STABLE_THRESHOLD_CANDIDATES = [0.01, 0.02, 0.03, 0.05, 0.10]


@dataclass(frozen=True)
class TargetMetrics:
    station_id: int
    commodity_name: str
    pair_count: int
    median_abs_price_change: float | None
    p95_abs_price_change: float | None
    nonzero_change_ratio: float | None
    max_abs_price_change: float | None
    forecast_error_median: float | None
    forecast_error_sample_count: int


def collect_target_metrics(
    session: Session,
    targets: list[tuple[int, str]],
    window_start: dt.datetime,
    now: dt.datetime,
    checkpoints: list[dt.datetime],
    window_days: int,
    horizon: dt.timedelta,
) -> tuple[list[TargetMetrics], dict[tuple[int, str], list[ReplaySample]]]:
    """Computes all CANDIDATE_METRICS for every target directly from
    MarketHistoricalObservation, reusing
    app.market.volatility.pair_observations/price_change_ratio (never
    re-implementing price pairing) -- and deliberately never calls
    app.market.predictability._compute_volatility_stats() or touches
    MarketPredictability, keeping this evaluation fully independent of
    the production path (spec §16.4). Also returns each target's raw
    ReplaySamples, collected once here and reused by
    sweep_metric_thresholds() for checkpoint-level reclassification
    rather than re-querying."""
    target_metrics: list[TargetMetrics] = []
    samples_by_target: dict[tuple[int, str], list[ReplaySample]] = {}

    for station_id, commodity_name in targets:
        rows = (
            session.query(MarketHistoricalObservation)
            .filter_by(station_id=station_id, commodity_name=commodity_name)
            .filter(MarketHistoricalObservation.observed_at >= window_start)
            .filter(MarketHistoricalObservation.observed_at <= now)
            .order_by(MarketHistoricalObservation.observed_at.asc())
            .all()
        )
        observations = [Observation(observed_at=r.observed_at, price=r.sell_price, demand=r.demand) for r in rows]
        pairs, _gaps = pair_observations(observations, MAX_OBSERVATION_GAP)
        changes = [c for c in (price_change_ratio(prev, curr) for prev, curr in pairs) if c is not None]

        median_change, p95_change = median_and_p95(changes)
        nonzero_ratio = (sum(1 for c in changes if c > 0) / len(changes)) if changes else None
        max_change = max(changes) if changes else None

        collection = collect_replay_samples(session, station_id, commodity_name, checkpoints, window_days, horizon)
        samples_by_target[(station_id, commodity_name)] = collection.samples
        errors = [s.forecast_error for s in collection.samples if s.forecast_error is not None]

        target_metrics.append(
            TargetMetrics(
                station_id=station_id,
                commodity_name=commodity_name,
                pair_count=len(changes),
                median_abs_price_change=median_change,
                p95_abs_price_change=p95_change,
                nonzero_change_ratio=nonzero_ratio,
                max_abs_price_change=max_change,
                forecast_error_median=statistics.median(errors) if errors else None,
                forecast_error_sample_count=len(errors),
            )
        )

    return target_metrics, samples_by_target


def spearman_correlation(xs: list[float], ys: list[float]) -> float | None:
    """Rank-transform + Pearson correlation, no external dependency.
    None for fewer than 4 pairs -- an explicit placeholder minimum, not
    a statistically derived one."""
    if len(xs) < 4 or len(xs) != len(ys):
        return None

    def rank(values: list[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        ranks = [0.0] * len(values)
        for position, index in enumerate(order):
            ranks[index] = float(position)
        return ranks

    try:
        return statistics.correlation(rank(xs), rank(ys))
    except statistics.StatisticsError:
        return None


def compute_metric_correlations(target_metrics: list[TargetMetrics]) -> dict[str, float | None]:
    """Spec §16.1. Spearman correlation between each CANDIDATE_METRICS
    value and forecast_error_median, across targets where both are
    present. Diagnostic only -- never selects a metric by itself."""
    with_error = [t for t in target_metrics if t.forecast_error_median is not None]
    result: dict[str, float | None] = {}
    for metric_name in CANDIDATE_METRICS:
        pairs = [
            (getattr(t, metric_name), t.forecast_error_median)
            for t in with_error
            if getattr(t, metric_name) is not None
        ]
        if not pairs:
            result[metric_name] = None
            continue
        xs = [x for x, _ in pairs]
        ys = [y for _, y in pairs]
        result[metric_name] = spearman_correlation(xs, ys)
    return result


def classify_by_metric(
    value: float | None,
    sample_count: int,
    stable_threshold: float,
    moderate_threshold: float,
    min_samples: int = MIN_SAMPLES_FOR_CLASSIFICATION,
) -> VolatilityClass:
    """Generic version of app.market.predictability.classify() -- takes
    an arbitrary metric value + threshold pair instead of being
    hardcoded to median_abs_price_change/STABLE_MEDIAN_PRICE_CHANGE/
    MODERATE_MEDIAN_PRICE_CHANGE. Never called by production code."""
    if sample_count < min_samples or value is None:
        return "INSUFFICIENT"
    if value < stable_threshold:
        return "STABLE"
    if value < moderate_threshold:
        return "MODERATE"
    return "VOLATILE"


@dataclass(frozen=True)
class ThresholdSweepResult:
    metric_name: str
    stable_threshold: float
    moderate_threshold: float
    class_stats: dict[VolatilityClass, ClassForecastErrorStats]
    ordering: OrderingHypothesisResult
    # Deliberately no adoption/decision field -- sweep_metric_thresholds()
    # never decides which threshold to adopt (spec §16.5). Only
    # docs/PHASE_2_6E...§7's human-reviewed adoption procedure may.


def sweep_metric_thresholds(
    target_metrics: list[TargetMetrics],
    samples_by_target: dict[tuple[int, str], list[ReplaySample]],
    metric_name: str,
    threshold_candidates: list[tuple[float, float]],
    min_samples: int = MIN_SAMPLES_FOR_CLASSIFICATION,
) -> list[ThresholdSweepResult]:
    """Spec §16.2/16.3/16.4. For each (stable_threshold,
    moderate_threshold) candidate, reclassifies every target by
    `metric_name` via classify_by_metric(), then pools that target's
    ReplaySample forecast_errors into the resulting class (checkpoint-
    level granularity, not just each target's own median -- more
    statistically meaningful than comparing 20 target-level medians).
    Aggregation reuses app.market.volatility.median_and_p95 and
    evaluate_ordering_hypothesis() unchanged, exactly as 2-6B's
    production-metric path already does -- no duplicated statistics."""
    results: list[ThresholdSweepResult] = []
    for stable_threshold, moderate_threshold in threshold_candidates:
        errors_by_class: dict[VolatilityClass, list[float]] = {}
        missing_by_class: dict[VolatilityClass, int] = {}

        for metrics in target_metrics:
            value = getattr(metrics, metric_name)
            volatility_class = classify_by_metric(
                value, metrics.pair_count, stable_threshold, moderate_threshold, min_samples
            )
            samples = samples_by_target.get((metrics.station_id, metrics.commodity_name), [])
            for sample in samples:
                if sample.forecast_error is None:
                    missing_by_class[volatility_class] = missing_by_class.get(volatility_class, 0) + 1
                    errors_by_class.setdefault(volatility_class, [])
                else:
                    errors_by_class.setdefault(volatility_class, []).append(sample.forecast_error)

        class_stats: dict[VolatilityClass, ClassForecastErrorStats] = {}
        for volatility_class in set(errors_by_class) | set(missing_by_class):
            errors = errors_by_class.get(volatility_class, [])
            median_error, p95_error = median_and_p95(errors)
            class_stats[volatility_class] = ClassForecastErrorStats(
                volatility_class=volatility_class,
                sample_count=len(errors),
                missing_actual_count=missing_by_class.get(volatility_class, 0),
                median_forecast_error=median_error,
                p95_forecast_error=p95_error,
            )

        results.append(
            ThresholdSweepResult(
                metric_name=metric_name,
                stable_threshold=stable_threshold,
                moderate_threshold=moderate_threshold,
                class_stats=class_stats,
                ordering=evaluate_ordering_hypothesis(class_stats),
            )
        )
    return results
