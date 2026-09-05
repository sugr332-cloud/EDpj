from __future__ import annotations

import dataclasses
import datetime as dt

from app.backtest.replay import ActualObservation, PredictionInput, ReplaySample, generate_t0_checkpoints
from app.backtest.volatility_evaluation import ClassForecastErrorStats, OrderingHypothesisResult, evaluate_ordering_hypothesis
from app.backtest.volatility_metric_evaluation import (
    CANDIDATE_METRICS,
    STABLE_THRESHOLD_CANDIDATES,
    ThresholdSweepResult,
    classify_by_metric,
    collect_target_metrics,
    compute_metric_correlations,
    spearman_correlation,
    sweep_metric_thresholds,
)
from app.db.models.market import MarketHistoricalObservation, MarketPredictability
from app.market.predictability import MIN_SAMPLES_FOR_CLASSIFICATION

T0 = dt.datetime(2026, 8, 20, 12, 0, tzinfo=dt.timezone.utc)


def _insert(session, station_id: int, commodity_name: str, observed_at: dt.datetime, price: int, demand: int = 100):
    session.add(
        MarketHistoricalObservation(
            station_id=station_id, commodity_name=commodity_name, sell_price=price, demand=demand,
            observed_at=observed_at,
        )
    )
    session.commit()


class TestCollectTargetMetrics:
    def test_computes_all_four_metrics_from_real_price_pairs(self, db_session):
        # prices: 100 -> 100 -> 110 -> 110 (pairs: 0, 0.1, 0)
        for i, price in enumerate([100, 100, 110, 110]):
            _insert(db_session, 100, "platinum", T0 + dt.timedelta(hours=i), price)

        window_start = T0 - dt.timedelta(days=1)
        now = T0 + dt.timedelta(hours=10)
        checkpoints = generate_t0_checkpoints(window_start, now, dt.timedelta(hours=6))

        metrics, samples_by_target = collect_target_metrics(
            db_session, [(100, "platinum")], window_start, now, checkpoints, window_days=1, horizon=dt.timedelta(hours=1)
        )

        m = metrics[0]
        assert m.pair_count == 3
        assert m.nonzero_change_ratio == 1 / 3
        assert m.max_abs_price_change > 0
        assert (100, "platinum") in samples_by_target

    def test_never_touches_market_predictability(self, db_session):
        for i, price in enumerate([100, 105, 100]):
            _insert(db_session, 100, "platinum", T0 + dt.timedelta(hours=i), price)
        window_start = T0 - dt.timedelta(days=1)
        now = T0 + dt.timedelta(hours=10)
        checkpoints = generate_t0_checkpoints(window_start, now, dt.timedelta(hours=6))

        collect_target_metrics(
            db_session, [(100, "platinum")], window_start, now, checkpoints, window_days=1, horizon=dt.timedelta(hours=1)
        )

        assert db_session.query(MarketPredictability).count() == 0

    def test_forecast_error_stats_match_collect_replay_samples(self, db_session):
        import statistics as st

        from app.backtest.replay import collect_replay_samples

        for i, price in enumerate([100, 105, 110, 108, 112]):
            _insert(db_session, 100, "platinum", T0 + dt.timedelta(hours=i * 2), price)
        window_start = T0 - dt.timedelta(days=1)
        now = T0 + dt.timedelta(hours=12)
        checkpoints = generate_t0_checkpoints(window_start, now, dt.timedelta(hours=3))

        metrics, _ = collect_target_metrics(
            db_session, [(100, "platinum")], window_start, now, checkpoints, window_days=1, horizon=dt.timedelta(hours=1)
        )
        direct_collection = collect_replay_samples(db_session, 100, "platinum", checkpoints, 1, dt.timedelta(hours=1))
        direct_errors = [s.forecast_error for s in direct_collection.samples if s.forecast_error is not None]

        assert metrics[0].forecast_error_sample_count == len(direct_errors)
        if direct_errors:
            assert metrics[0].forecast_error_median == st.median(direct_errors)


class TestSpearmanCorrelation:
    def test_none_when_fewer_than_four_pairs(self):
        assert spearman_correlation([1, 2, 3], [1, 2, 3]) is None

    def test_perfect_positive_correlation(self):
        assert spearman_correlation([1, 2, 3, 4, 5], [10, 20, 30, 40, 50]) == 1.0

    def test_perfect_negative_correlation(self):
        assert spearman_correlation([1, 2, 3, 4, 5], [50, 40, 30, 20, 10]) == -1.0

    def test_mismatched_lengths_returns_none(self):
        assert spearman_correlation([1, 2, 3, 4], [1, 2, 3]) is None


class TestComputeMetricCorrelations:
    def test_returns_all_candidate_metrics(self):
        from app.backtest.volatility_metric_evaluation import TargetMetrics

        targets = [
            TargetMetrics(100, f"c{i}", 10, med, med, med, med, err, 5)
            for i, (med, err) in enumerate(zip([0.01, 0.02, 0.03, 0.04, 0.05], [0.1, 0.2, 0.3, 0.4, 0.5]))
        ]

        correlations = compute_metric_correlations(targets)

        assert set(correlations.keys()) == set(CANDIDATE_METRICS)
        assert correlations["median_abs_price_change"] == 1.0  # perfectly monotonic by construction


class TestClassifyByMetric:
    def test_insufficient_when_sample_count_too_low_regardless_of_value(self):
        assert classify_by_metric(0.5, sample_count=1, stable_threshold=0.05, moderate_threshold=0.15) == "INSUFFICIENT"

    def test_stable_below_threshold(self):
        assert classify_by_metric(0.01, MIN_SAMPLES_FOR_CLASSIFICATION, 0.05, 0.15) == "STABLE"

    def test_moderate_between_thresholds(self):
        assert classify_by_metric(0.10, MIN_SAMPLES_FOR_CLASSIFICATION, 0.05, 0.15) == "MODERATE"

    def test_volatile_at_or_above_moderate_threshold(self):
        assert classify_by_metric(0.20, MIN_SAMPLES_FOR_CLASSIFICATION, 0.05, 0.15) == "VOLATILE"

    def test_never_imports_production_constants(self):
        # Structural guarantee (spec §16.4): this module must not depend
        # on app.market.predictability's STABLE_MEDIAN_PRICE_CHANGE/
        # MODERATE_MEDIAN_PRICE_CHANGE/classify().
        import app.backtest.volatility_metric_evaluation as mod

        source_names = dir(mod)
        assert "STABLE_MEDIAN_PRICE_CHANGE" not in source_names
        assert "MODERATE_MEDIAN_PRICE_CHANGE" not in source_names


def _sample(volatility_class: str, forecast_error: float | None) -> ReplaySample:
    prediction = PredictionInput(
        t0=T0, predicted_price=100.0, predicted_price_observed_at=T0, volatility_class=volatility_class,
        sample_count_at_t0=99,
    )
    actual = None if forecast_error is None else ActualObservation(observed_at=T0 + dt.timedelta(hours=1), actual_price=100.0)
    return ReplaySample(prediction=prediction, actual=actual, horizon=dt.timedelta(hours=1), forecast_error=forecast_error)


class TestSweepMetricThresholds:
    def _target_metrics(self, station_id, commodity_name, value):
        from app.backtest.volatility_metric_evaluation import TargetMetrics

        return TargetMetrics(
            station_id=station_id, commodity_name=commodity_name, pair_count=MIN_SAMPLES_FOR_CLASSIFICATION,
            median_abs_price_change=value, p95_abs_price_change=value, nonzero_change_ratio=value,
            max_abs_price_change=value, forecast_error_median=None, forecast_error_sample_count=0,
        )

    def test_one_result_per_threshold_candidate(self):
        target_metrics = [self._target_metrics(100, "a", 0.02)]
        samples_by_target = {(100, "a"): [_sample("STABLE", 0.01)] * MIN_SAMPLES_FOR_CLASSIFICATION}

        results = sweep_metric_thresholds(
            target_metrics, samples_by_target, "median_abs_price_change",
            [(0.01, 0.03), (0.05, 0.15)],
        )

        assert len(results) == 2
        assert [(r.stable_threshold, r.moderate_threshold) for r in results] == [(0.01, 0.03), (0.05, 0.15)]

    def test_reuses_evaluate_ordering_hypothesis_unchanged(self):
        target_metrics = [
            self._target_metrics(100, "stable_target", 0.01),
            self._target_metrics(100, "moderate_target", 0.08),
            self._target_metrics(100, "volatile_target", 0.20),
        ]
        samples_by_target = {
            (100, "stable_target"): [_sample("dummy", 0.01)] * 40,
            (100, "moderate_target"): [_sample("dummy", 0.1)] * 40,
            (100, "volatile_target"): [_sample("dummy", 0.5)] * 40,
        }

        results = sweep_metric_thresholds(
            target_metrics, samples_by_target, "median_abs_price_change", [(0.05, 0.15)],
            min_samples=1,
        )

        direct = evaluate_ordering_hypothesis(results[0].class_stats)
        assert results[0].ordering == direct

    def test_no_decision_field_on_result(self):
        field_names = {f.name for f in dataclasses.fields(ThresholdSweepResult)}
        assert not any("decision" in name for name in field_names)

    def test_default_stable_threshold_candidates_use_three_x_ratio(self):
        assert STABLE_THRESHOLD_CANDIDATES == [0.01, 0.02, 0.03, 0.05, 0.10]
