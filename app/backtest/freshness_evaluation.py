"""Freshness curve evaluation — Phase 2-6C.

Spec (docs/PHASE_2_6C_FRESHNESS_EVALUATION_IMPLEMENTATION_BASELINE_V0.1.md).
Groups the same ReplaySamples Phase 2-6B consumes
(app.backtest.replay.collect_replay_samples) by how stale the
observation backing each prediction was at T0, and checks whether
forecast error actually gets worse as that staleness increases -- the
structural assumption behind app.scoring.confidence's freshness curve.
This module does not decide FRESHNESS_FULL_THRESHOLD/
FRESHNESS_FLOOR_THRESHOLD/FRESHNESS_FLOOR's values or the curve's shape;
that's Phase 2-6E's job once real data is examined (spec §0).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from app.backtest.replay import ReplaySample
from app.backtest.volatility_evaluation import MIN_SAMPLES_FOR_EVALUATION
from app.market.volatility import median_and_p95
from app.scoring.confidence import FRESHNESS_FLOOR_THRESHOLD, FRESHNESS_FULL_THRESHOLD

# The two ends are shared with app/scoring/confidence.py's curve
# breakpoints (spec §2) so the buckets this module measures against
# include the exact boundaries the current curve uses. The points in
# between exist so 2-6C can tell a genuinely linear decay from any other
# shape -- the current curve's 3-piece (<15m / 15m-24h / >=24h) shape
# alone can't distinguish those (spec §2).
AGE_BUCKET_BOUNDARIES: list[dt.timedelta] = [
    FRESHNESS_FULL_THRESHOLD,  # 15 minutes
    dt.timedelta(minutes=30),
    dt.timedelta(hours=1),
    dt.timedelta(hours=3),
    dt.timedelta(hours=6),
    dt.timedelta(hours=12),
    FRESHNESS_FLOOR_THRESHOLD,  # 24 hours
]

FRESHNESS_BUCKET_ORDER: list[str] = [
    "<15m",
    "15m-30m",
    "30m-1h",
    "1h-3h",
    "3h-6h",
    "6h-12h",
    "12h-24h",
    ">=24h",
]


def _naive(ts: dt.datetime) -> dt.datetime:
    # Same SQLite tz round-trip workaround as app/backtest/replay.py and
    # app/scoring/confidence.py -- duplicated per-module by existing
    # project convention rather than centralized.
    return ts.replace(tzinfo=None) if ts.tzinfo is not None else ts


def age_at_t0(sample: ReplaySample) -> dt.timedelta:
    """How stale the observation backing `sample.prediction` was at T0
    -- the same quantity app.scoring.confidence.market_freshness()
    computes as `now - observed_at`, with T0 standing in for `now`.
    Always >= 0: predict_naive_persistence() only ever selects
    observations with `observed_at <= t0` (docs/PHASE_2_6A...§4.1), so
    there's no negative-age case to handle."""
    return _naive(sample.prediction.t0) - _naive(sample.prediction.predicted_price_observed_at)


def classify_freshness_bucket(age: dt.timedelta) -> str:
    """Linear scan against AGE_BUCKET_BOUNDARIES; each boundary is an
    exclusive upper bound for the bucket below it, so a value exactly on
    a boundary falls into the *next* (older) bucket -- never double
    counted."""
    for boundary, label in zip(AGE_BUCKET_BOUNDARIES, FRESHNESS_BUCKET_ORDER):
        if age < boundary:
            return label
    return FRESHNESS_BUCKET_ORDER[-1]


@dataclass(frozen=True)
class FreshnessBucketStats:
    freshness_bucket: str
    sample_count: int  # ReplaySamples in this bucket with forecast_error is not None
    missing_actual_count: int  # ReplaySamples in this bucket with forecast_error is None
    median_forecast_error: float | None
    p95_forecast_error: float | None


def aggregate_by_freshness_bucket(samples: list[ReplaySample]) -> dict[str, FreshnessBucketStats]:
    """Same aggregation shape as
    app.backtest.volatility_evaluation.aggregate_by_volatility_class --
    median/p95 via app.market.volatility.median_and_p95, samples with
    forecast_error=None counted but excluded from the median/p95 input,
    a bucket that never occurs simply absent from the result (never a
    synthesized zero-sample entry). Kept as an independent
    implementation rather than sharing a generic grouping helper with
    2-6B: the grouping key's type differs (VolatilityClass vs. a
    freshness bucket label) and there are only these two call sites, so
    forcing a shared abstraction now would cost more clarity than the
    ~20 duplicated lines it would save."""
    errors_by_bucket: dict[str, list[float]] = {}
    missing_by_bucket: dict[str, int] = {}
    for sample in samples:
        bucket = classify_freshness_bucket(age_at_t0(sample))
        if sample.forecast_error is None:
            missing_by_bucket[bucket] = missing_by_bucket.get(bucket, 0) + 1
            errors_by_bucket.setdefault(bucket, [])
            continue
        errors_by_bucket.setdefault(bucket, []).append(sample.forecast_error)

    all_buckets = set(errors_by_bucket) | set(missing_by_bucket)
    result: dict[str, FreshnessBucketStats] = {}
    for bucket in all_buckets:
        errors = errors_by_bucket.get(bucket, [])
        median_error, p95_error = median_and_p95(errors)
        result[bucket] = FreshnessBucketStats(
            freshness_bucket=bucket,
            sample_count=len(errors),
            missing_actual_count=missing_by_bucket.get(bucket, 0),
            median_forecast_error=median_error,
            p95_forecast_error=p95_error,
        )
    return result


@dataclass(frozen=True)
class FreshnessMonotonicityResult:
    bucket_stats: dict[str, FreshnessBucketStats]
    pairwise_non_decreasing: dict[tuple[str, str], bool | None]
    overall_monotonic: bool | None


def _sufficient(stats: FreshnessBucketStats | None) -> bool:
    return stats is not None and stats.sample_count >= MIN_SAMPLES_FOR_EVALUATION


def evaluate_freshness_monotonicity(
    bucket_stats: dict[str, FreshnessBucketStats],
) -> FreshnessMonotonicityResult:
    """Checks, for each adjacent pair in FRESHNESS_BUCKET_ORDER, whether
    median_forecast_error is non-decreasing (older bucket's median >=
    younger bucket's median) -- the structural assumption behind the
    freshness curve's decay, not its specific numeric values (spec §0).
    Never repositions AGE_BUCKET_BOUNDARIES itself; that's Phase 2-6E's
    job, same as 2-6B's evaluate_ordering_hypothesis() never repositions
    the volatility thresholds.

    A pair where either side has sample_count < MIN_SAMPLES_FOR_EVALUATION
    (including a bucket that's entirely absent) maps to None -- never
    collapsed into False, so "not enough data to judge" can never look
    like "hypothesis rejected".

    overall_monotonic is None only when there isn't a single evaluable
    pair (§4); otherwise True iff every evaluable pair is True, False if
    any evaluable pair is False."""
    pairwise: dict[tuple[str, str], bool | None] = {}
    for younger, older in zip(FRESHNESS_BUCKET_ORDER, FRESHNESS_BUCKET_ORDER[1:]):
        younger_stats = bucket_stats.get(younger)
        older_stats = bucket_stats.get(older)
        if _sufficient(younger_stats) and _sufficient(older_stats):
            pairwise[(younger, older)] = younger_stats.median_forecast_error <= older_stats.median_forecast_error
        else:
            pairwise[(younger, older)] = None

    evaluable = [holds for holds in pairwise.values() if holds is not None]
    overall_monotonic = all(evaluable) if evaluable else None

    return FreshnessMonotonicityResult(
        bucket_stats=bucket_stats, pairwise_non_decreasing=pairwise, overall_monotonic=overall_monotonic
    )
