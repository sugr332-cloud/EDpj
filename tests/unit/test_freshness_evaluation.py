from __future__ import annotations

import datetime as dt

from app.backtest.freshness_evaluation import (
    AGE_BUCKET_BOUNDARIES,
    FRESHNESS_BUCKET_ORDER,
    FreshnessBucketStats,
    age_at_t0,
    aggregate_by_freshness_bucket,
    classify_freshness_bucket,
    evaluate_freshness_monotonicity,
)
from app.backtest.replay import ActualObservation, PredictionInput, ReplaySample
from app.backtest.volatility_evaluation import MIN_SAMPLES_FOR_EVALUATION
from app.scoring.confidence import FRESHNESS_FLOOR_THRESHOLD, FRESHNESS_FULL_THRESHOLD

T0 = dt.datetime(2026, 8, 20, 12, 0, tzinfo=dt.timezone.utc)


def _sample(age: dt.timedelta, forecast_error: float | None) -> ReplaySample:
    prediction = PredictionInput(
        t0=T0,
        predicted_price=100.0,
        predicted_price_observed_at=T0 - age,
        volatility_class="STABLE",
        sample_count_at_t0=99,
    )
    actual = (
        None
        if forecast_error is None
        else ActualObservation(observed_at=T0 + dt.timedelta(hours=1), actual_price=100.0)
    )
    return ReplaySample(prediction=prediction, actual=actual, horizon=dt.timedelta(hours=1), forecast_error=forecast_error)


class TestAgeAtT0:
    def test_computes_gap_between_t0_and_predicted_price_observed_at(self):
        sample = _sample(dt.timedelta(hours=2), forecast_error=0.1)
        assert age_at_t0(sample) == dt.timedelta(hours=2)

    def test_zero_age_when_observation_is_exactly_at_t0(self):
        sample = _sample(dt.timedelta(0), forecast_error=0.1)
        assert age_at_t0(sample) == dt.timedelta(0)

    def test_handles_naive_and_aware_datetimes_mixed(self):
        # Simulates SQLite's tz round-trip: predicted_price_observed_at
        # comes back naive even though t0 is tz-aware.
        prediction = PredictionInput(
            t0=T0,
            predicted_price=100.0,
            predicted_price_observed_at=(T0 - dt.timedelta(hours=3)).replace(tzinfo=None),
            volatility_class="STABLE",
            sample_count_at_t0=10,
        )
        sample = ReplaySample(prediction=prediction, actual=None, horizon=dt.timedelta(hours=1), forecast_error=None)
        assert age_at_t0(sample) == dt.timedelta(hours=3)


class TestClassifyFreshnessBucket:
    def test_boundaries_match_confidence_curve(self):
        assert AGE_BUCKET_BOUNDARIES[0] == FRESHNESS_FULL_THRESHOLD
        assert AGE_BUCKET_BOUNDARIES[-1] == FRESHNESS_FLOOR_THRESHOLD

    def test_zero_age_is_youngest_bucket(self):
        assert classify_freshness_bucket(dt.timedelta(0)) == "<15m"

    def test_value_exactly_on_a_boundary_falls_into_the_older_bucket(self):
        # Exclusive upper bound: age == FRESHNESS_FULL_THRESHOLD is not
        # "< 15m" anymore, so it must not double-count into <15m.
        assert classify_freshness_bucket(FRESHNESS_FULL_THRESHOLD) == "15m-30m"

    def test_value_just_under_a_boundary_stays_in_the_younger_bucket(self):
        assert classify_freshness_bucket(FRESHNESS_FULL_THRESHOLD - dt.timedelta(seconds=1)) == "<15m"

    def test_age_at_or_past_floor_threshold_is_the_oldest_bucket(self):
        assert classify_freshness_bucket(FRESHNESS_FLOOR_THRESHOLD) == ">=24h"
        assert classify_freshness_bucket(FRESHNESS_FLOOR_THRESHOLD + dt.timedelta(days=10)) == ">=24h"

    def test_every_boundary_maps_to_a_distinct_label_in_order(self):
        labels = [classify_freshness_bucket(b) for b in AGE_BUCKET_BOUNDARIES]
        assert labels == FRESHNESS_BUCKET_ORDER[1:]  # each boundary belongs to the *next* bucket


class TestAggregateByFreshnessBucket:
    def test_groups_by_bucket(self):
        samples = [
            _sample(dt.timedelta(minutes=1), 0.01),
            _sample(dt.timedelta(minutes=2), 0.02),
            _sample(dt.timedelta(hours=20), 0.5),
        ]

        result = aggregate_by_freshness_bucket(samples)

        assert result["<15m"].sample_count == 2
        assert result["12h-24h"].sample_count == 1

    def test_missing_actual_excluded_from_median_but_counted(self):
        samples = [_sample(dt.timedelta(minutes=1), 0.01), _sample(dt.timedelta(minutes=2), None)]

        result = aggregate_by_freshness_bucket(samples)

        assert result["<15m"].sample_count == 1
        assert result["<15m"].missing_actual_count == 1
        assert result["<15m"].median_forecast_error == 0.01

    def test_bucket_that_never_appears_is_absent_not_a_zero_entry(self):
        samples = [_sample(dt.timedelta(minutes=1), 0.01)]

        result = aggregate_by_freshness_bucket(samples)

        assert ">=24h" not in result

    def test_median_and_p95_reuse_the_shared_volatility_helper(self):
        from app.market.volatility import median_and_p95

        errors = [0.01, 0.05, 0.1, 0.2, 0.3]
        samples = [_sample(dt.timedelta(hours=2), e) for e in errors]

        result = aggregate_by_freshness_bucket(samples)
        expected_median, expected_p95 = median_and_p95(errors)

        assert result["1h-3h"].median_forecast_error == expected_median
        assert result["1h-3h"].p95_forecast_error == expected_p95


def _stats(bucket: str, sample_count: int, median_error: float | None) -> FreshnessBucketStats:
    return FreshnessBucketStats(
        freshness_bucket=bucket, sample_count=sample_count, missing_actual_count=0,
        median_forecast_error=median_error, p95_forecast_error=median_error,
    )


class TestEvaluateFreshnessMonotonicity:
    def test_overall_true_when_every_evaluable_pair_is_non_decreasing(self):
        bucket_stats = {
            "<15m": _stats("<15m", MIN_SAMPLES_FOR_EVALUATION, 0.01),
            "15m-30m": _stats("15m-30m", MIN_SAMPLES_FOR_EVALUATION, 0.02),
            "30m-1h": _stats("30m-1h", MIN_SAMPLES_FOR_EVALUATION, 0.03),
        }

        result = evaluate_freshness_monotonicity(bucket_stats)

        assert result.overall_monotonic is True
        assert result.pairwise_non_decreasing[("<15m", "15m-30m")] is True

    def test_overall_false_when_a_pair_decreases(self):
        bucket_stats = {
            "<15m": _stats("<15m", MIN_SAMPLES_FOR_EVALUATION, 0.5),
            "15m-30m": _stats("15m-30m", MIN_SAMPLES_FOR_EVALUATION, 0.1),
        }

        result = evaluate_freshness_monotonicity(bucket_stats)

        assert result.overall_monotonic is False
        assert result.pairwise_non_decreasing[("<15m", "15m-30m")] is False

    def test_pair_with_insufficient_samples_is_none_not_false(self):
        bucket_stats = {
            "<15m": _stats("<15m", MIN_SAMPLES_FOR_EVALUATION - 1, 0.5),  # insufficient
            "15m-30m": _stats("15m-30m", MIN_SAMPLES_FOR_EVALUATION, 0.1),
        }

        result = evaluate_freshness_monotonicity(bucket_stats)

        assert result.pairwise_non_decreasing[("<15m", "15m-30m")] is None

    def test_pair_with_an_entirely_absent_bucket_is_none(self):
        bucket_stats = {"<15m": _stats("<15m", MIN_SAMPLES_FOR_EVALUATION, 0.5)}  # 15m-30m never occurred

        result = evaluate_freshness_monotonicity(bucket_stats)

        assert result.pairwise_non_decreasing[("<15m", "15m-30m")] is None

    def test_overall_none_when_no_pair_is_evaluable(self):
        result = evaluate_freshness_monotonicity({})

        assert result.overall_monotonic is None

    def test_never_repositions_bucket_boundaries(self):
        # Structural guarantee, matching 2-6B's
        # evaluate_ordering_hypothesis(): no parameter exists through
        # which alternative AGE_BUCKET_BOUNDARIES could be passed in.
        import inspect

        params = list(inspect.signature(evaluate_freshness_monotonicity).parameters)
        assert params == ["bucket_stats"]
