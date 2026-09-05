from __future__ import annotations

import datetime as dt

import pytest

from app.backtest.replay import ActualObservation, PredictionInput, ReplaySample
from app.backtest.volatility_evaluation import (
    MIN_SAMPLES_FOR_EVALUATION,
    aggregate_by_volatility_class,
    evaluate_ordering_hypothesis,
)
from app.calibration.metrics import MAE_THRESHOLD

T0 = dt.datetime(2026, 8, 20, 12, 0, tzinfo=dt.timezone.utc)


def _sample(volatility_class: str, forecast_error: float | None) -> ReplaySample:
    prediction = PredictionInput(
        t0=T0,
        predicted_price=100.0,
        predicted_price_observed_at=T0,
        volatility_class=volatility_class,
        sample_count_at_t0=99,
    )
    actual = (
        None
        if forecast_error is None
        else ActualObservation(observed_at=T0 + dt.timedelta(hours=1), actual_price=100.0)
    )
    return ReplaySample(prediction=prediction, actual=actual, horizon=dt.timedelta(hours=1), forecast_error=forecast_error)


class TestAggregateByVolatilityClass:
    def test_groups_by_volatility_class(self):
        samples = [_sample("STABLE", 0.01), _sample("STABLE", 0.02), _sample("VOLATILE", 0.5)]

        result = aggregate_by_volatility_class(samples)

        assert result["STABLE"].sample_count == 2
        assert result["VOLATILE"].sample_count == 1

    def test_missing_actual_excluded_from_median_but_counted(self):
        samples = [_sample("STABLE", 0.01), _sample("STABLE", None)]

        result = aggregate_by_volatility_class(samples)

        assert result["STABLE"].sample_count == 1
        assert result["STABLE"].missing_actual_count == 1
        assert result["STABLE"].median_forecast_error == 0.01

    def test_class_that_never_appears_is_absent_not_a_zero_entry(self):
        samples = [_sample("STABLE", 0.01)]

        result = aggregate_by_volatility_class(samples)

        assert "VOLATILE" not in result

    def test_empty_input_produces_empty_result(self):
        assert aggregate_by_volatility_class([]) == {}

    def test_median_and_p95_reuse_the_shared_volatility_helper(self):
        from app.market.volatility import median_and_p95

        errors = [0.01, 0.05, 0.1, 0.2, 0.3]
        samples = [_sample("MODERATE", e) for e in errors]

        result = aggregate_by_volatility_class(samples)
        expected_median, expected_p95 = median_and_p95(errors)

        assert result["MODERATE"].median_forecast_error == expected_median
        assert result["MODERATE"].p95_forecast_error == expected_p95


class TestEvaluateOrderingHypothesis:
    def test_holds_when_medians_increase_and_samples_are_sufficient(self):
        samples = (
            [_sample("STABLE", 0.01)] * MIN_SAMPLES_FOR_EVALUATION
            + [_sample("MODERATE", 0.1)] * MIN_SAMPLES_FOR_EVALUATION
            + [_sample("VOLATILE", 0.5)] * MIN_SAMPLES_FOR_EVALUATION
        )

        result = evaluate_ordering_hypothesis(aggregate_by_volatility_class(samples))

        assert result.ordering_holds is True

    def test_fails_when_order_is_broken(self):
        samples = (
            [_sample("STABLE", 0.5)] * MIN_SAMPLES_FOR_EVALUATION
            + [_sample("MODERATE", 0.1)] * MIN_SAMPLES_FOR_EVALUATION
            + [_sample("VOLATILE", 0.01)] * MIN_SAMPLES_FOR_EVALUATION
        )

        result = evaluate_ordering_hypothesis(aggregate_by_volatility_class(samples))

        assert result.ordering_holds is False

    def test_none_when_a_class_has_too_few_samples(self):
        samples = (
            [_sample("STABLE", 0.01)] * (MIN_SAMPLES_FOR_EVALUATION - 1)  # one short of sufficient
            + [_sample("MODERATE", 0.1)] * MIN_SAMPLES_FOR_EVALUATION
            + [_sample("VOLATILE", 0.5)] * MIN_SAMPLES_FOR_EVALUATION
        )

        result = evaluate_ordering_hypothesis(aggregate_by_volatility_class(samples))

        assert result.ordering_holds is None  # never collapses to False when data is merely insufficient

    def test_none_when_a_class_is_entirely_absent(self):
        samples = [_sample("STABLE", 0.01)] * MIN_SAMPLES_FOR_EVALUATION + [
            _sample("VOLATILE", 0.5)
        ] * MIN_SAMPLES_FOR_EVALUATION  # no MODERATE samples at all

        result = evaluate_ordering_hypothesis(aggregate_by_volatility_class(samples))

        assert result.ordering_holds is None

    def test_stable_within_mae_threshold_true(self):
        samples = [_sample("STABLE", 0.05)] * MIN_SAMPLES_FOR_EVALUATION

        result = evaluate_ordering_hypothesis(aggregate_by_volatility_class(samples))

        assert MAE_THRESHOLD == pytest.approx(0.20)
        assert result.stable_within_mae_threshold is True

    def test_stable_within_mae_threshold_false_is_not_none(self):
        samples = [_sample("STABLE", 0.9)] * MIN_SAMPLES_FOR_EVALUATION

        result = evaluate_ordering_hypothesis(aggregate_by_volatility_class(samples))

        assert result.stable_within_mae_threshold is False

    def test_volatile_exceeds_mae_threshold_true(self):
        samples = [_sample("VOLATILE", 0.9)] * MIN_SAMPLES_FOR_EVALUATION

        result = evaluate_ordering_hypothesis(aggregate_by_volatility_class(samples))

        assert result.volatile_exceeds_mae_threshold is True

    def test_volatile_exceeds_mae_threshold_false_is_not_none(self):
        samples = [_sample("VOLATILE", 0.05)] * MIN_SAMPLES_FOR_EVALUATION

        result = evaluate_ordering_hypothesis(aggregate_by_volatility_class(samples))

        assert result.volatile_exceeds_mae_threshold is False

    def test_all_fields_none_when_no_classes_present(self):
        result = evaluate_ordering_hypothesis(aggregate_by_volatility_class([]))

        assert result.ordering_holds is None
        assert result.stable_within_mae_threshold is None
        assert result.volatile_exceeds_mae_threshold is None

    def test_never_repositions_thresholds(self):
        # Structural guarantee: evaluate_ordering_hypothesis has no
        # parameter through which alternative STABLE/MODERATE thresholds
        # could be passed in -- threshold repositioning is Phase 2-6E's
        # job (spec §0/§3), not something this function can do even by
        # accident.
        import inspect

        params = list(inspect.signature(evaluate_ordering_hypothesis).parameters)
        assert params == ["class_stats"]
