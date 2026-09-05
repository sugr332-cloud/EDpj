from __future__ import annotations

import datetime as dt

from app.backtest.replay import (
    DEFAULT_REPLAY_HORIZONS,
    compare_windows,
    evaluate_forecast_at,
    observe_actual_after,
    predict_naive_persistence,
)
from app.db.models.market import MarketHistoricalObservation, MarketPredictability
from app.scoring.confidence import FRESHNESS_FLOOR_THRESHOLD, FRESHNESS_FULL_THRESHOLD

T0 = dt.datetime(2026, 8, 20, 12, 0, tzinfo=dt.timezone.utc)


def _insert(session, station_id: int, commodity_name: str, observed_at: dt.datetime, price: int, demand: int = 100):
    session.add(
        MarketHistoricalObservation(
            station_id=station_id, commodity_name=commodity_name, sell_price=price, demand=demand,
            observed_at=observed_at,
        )
    )
    session.commit()


class TestPredictNaivePersistence:
    def test_returns_none_when_no_observation_at_or_before_t0(self, db_session):
        _insert(db_session, 100, "platinum", T0 + dt.timedelta(minutes=5), 40000)  # only future data
        assert predict_naive_persistence(db_session, 100, "platinum", T0, window_days=7) is None

    def test_uses_latest_observation_at_or_before_t0(self, db_session):
        _insert(db_session, 100, "platinum", T0 - dt.timedelta(hours=2), 39000)
        _insert(db_session, 100, "platinum", T0 - dt.timedelta(minutes=1), 40000)  # latest <= t0
        _insert(db_session, 100, "platinum", T0, 40000)

        prediction = predict_naive_persistence(db_session, 100, "platinum", T0, window_days=7)

        assert prediction is not None
        assert prediction.predicted_price == 40000
        # SQLite round-trips observed_at as naive even though it was
        # written tz-aware (same as app/scoring/confidence.py) -- compare
        # naive-to-naive rather than assuming both sides carry tzinfo.
        assert prediction.predicted_price_observed_at.replace(tzinfo=None) == T0.replace(tzinfo=None)

    def test_never_uses_an_observation_after_t0(self, db_session):
        # A future observation with a wildly different price must never
        # win over the true latest-at-or-before-t0 row.
        _insert(db_session, 100, "platinum", T0 - dt.timedelta(minutes=1), 40000)
        _insert(db_session, 100, "platinum", T0 + dt.timedelta(minutes=1), 999999)

        prediction = predict_naive_persistence(db_session, 100, "platinum", T0, window_days=7)

        assert prediction.predicted_price == 40000

    def test_volatility_class_matches_compute_volatility_stats_over_same_window(self, db_session):
        from app.market.predictability import _compute_volatility_stats

        for i in range(15):
            _insert(db_session, 100, "platinum", T0 - dt.timedelta(days=i), 40000 + i * 100)

        prediction = predict_naive_persistence(db_session, 100, "platinum", T0, window_days=7)
        direct = _compute_volatility_stats(
            db_session, station_id=100, commodity_name="platinum", window_start=T0 - dt.timedelta(days=7), now=T0
        )

        assert prediction.volatility_class == direct.volatility_class
        assert prediction.sample_count_at_t0 == direct.sample_count


class TestObserveActualAfter:
    def test_returns_none_when_nothing_after_t0(self, db_session):
        _insert(db_session, 100, "platinum", T0 - dt.timedelta(minutes=5), 40000)
        assert observe_actual_after(db_session, 100, "platinum", T0, dt.timedelta(hours=1)) is None

    def test_ignores_observation_exactly_at_t0(self, db_session):
        # observed_at == t0 must not count as "actual" -- it's the same
        # instant the prediction is made from, not something in the future.
        _insert(db_session, 100, "platinum", T0, 40000)
        assert observe_actual_after(db_session, 100, "platinum", T0, dt.timedelta(hours=1)) is None

    def test_picks_the_observation_nearest_the_target(self, db_session):
        horizon = dt.timedelta(hours=1)
        _insert(db_session, 100, "platinum", T0 + dt.timedelta(minutes=30), 41000)  # far from target
        _insert(db_session, 100, "platinum", T0 + dt.timedelta(minutes=58), 42000)  # nearest to t0+1h
        _insert(db_session, 100, "platinum", T0 + dt.timedelta(hours=3), 43000)  # outside max_gap window

        actual = observe_actual_after(db_session, 100, "platinum", T0, horizon, max_gap=dt.timedelta(hours=1))

        assert actual.actual_price == 42000

    def test_returns_none_when_gap_exceeds_max_gap(self, db_session):
        _insert(db_session, 100, "platinum", T0 + dt.timedelta(hours=10), 40000)
        actual = observe_actual_after(
            db_session, 100, "platinum", T0, dt.timedelta(hours=1), max_gap=dt.timedelta(hours=1)
        )
        assert actual is None


class TestEvaluateForecastAt:
    def test_returns_none_when_no_prediction_input(self, db_session):
        assert evaluate_forecast_at(db_session, 100, "platinum", T0, window_days=7, horizon=dt.timedelta(hours=1)) is None

    def test_forecast_error_is_none_when_no_actual_found(self, db_session):
        _insert(db_session, 100, "platinum", T0 - dt.timedelta(minutes=1), 40000)

        sample = evaluate_forecast_at(db_session, 100, "platinum", T0, window_days=7, horizon=dt.timedelta(hours=1))

        assert sample is not None
        assert sample.actual is None
        assert sample.forecast_error is None  # never 0 or interpolated

    def test_forecast_error_computed_from_predicted_and_actual_price(self, db_session):
        _insert(db_session, 100, "platinum", T0 - dt.timedelta(minutes=1), 40000)
        _insert(db_session, 100, "platinum", T0 + dt.timedelta(minutes=59), 44000)

        sample = evaluate_forecast_at(db_session, 100, "platinum", T0, window_days=7, horizon=dt.timedelta(hours=1))

        assert sample.prediction.predicted_price == 40000
        assert sample.actual.actual_price == 44000
        assert sample.forecast_error == abs(44000 - 40000) / 40000

    def test_forecast_error_is_none_when_predicted_price_is_zero(self, db_session):
        _insert(db_session, 100, "platinum", T0 - dt.timedelta(minutes=1), 0)
        _insert(db_session, 100, "platinum", T0 + dt.timedelta(minutes=59), 44000)

        sample = evaluate_forecast_at(db_session, 100, "platinum", T0, window_days=7, horizon=dt.timedelta(hours=1))

        assert sample.forecast_error is None


class TestFutureLeakagePrevention:
    """The strongest leak check: build a fixture with data before T0, at
    T0, and after T0, record PredictionInput, then add MORE future data
    and assert PredictionInput is byte-for-byte unchanged. A prediction
    that silently drifted when unrelated future rows were inserted would
    indicate some query in the prediction path isn't actually bounded by
    `observed_at <= t0`."""

    def test_prediction_input_unchanged_after_adding_future_observations(self, db_session):
        _insert(db_session, 100, "platinum", T0 - dt.timedelta(days=1), 39000)
        _insert(db_session, 100, "platinum", T0 - dt.timedelta(hours=1), 40000)
        _insert(db_session, 100, "platinum", T0, 40500)  # exactly at T0 -- allowed to be the prediction basis

        before = predict_naive_persistence(db_session, 100, "platinum", T0, window_days=7)
        assert before is not None

        # Now add a large amount of future data, including data timed to
        # be the "obvious" next observation and wildly different prices.
        _insert(db_session, 100, "platinum", T0 + dt.timedelta(seconds=1), 999999)
        _insert(db_session, 100, "platinum", T0 + dt.timedelta(minutes=5), 1)
        for i in range(1, 20):
            _insert(db_session, 100, "platinum", T0 + dt.timedelta(hours=i), 100000 + i)

        after = predict_naive_persistence(db_session, 100, "platinum", T0, window_days=7)

        assert after == before

    def test_actual_observation_unaffected_by_data_far_before_t0(self, db_session):
        _insert(db_session, 100, "platinum", T0 - dt.timedelta(days=100), 1)  # ancient, irrelevant
        _insert(db_session, 100, "platinum", T0 + dt.timedelta(minutes=30), 45000)

        before = observe_actual_after(db_session, 100, "platinum", T0, dt.timedelta(hours=1))

        _insert(db_session, 100, "platinum", T0 - dt.timedelta(hours=1), 999999)  # more past noise

        after = observe_actual_after(db_session, 100, "platinum", T0, dt.timedelta(hours=1))

        assert after == before


class TestCompareWindows:
    def test_independent_windows_can_produce_different_results(self, db_session):
        # Only the last 7 days have price movement; days 8-30 are flat at
        # a very different price level, so 7/14/30-day windows should not
        # coincide.
        for i in range(7):
            _insert(db_session, 100, "platinum", T0 - dt.timedelta(days=i), 40000 + i * 5000)
        for i in range(7, 30):
            _insert(db_session, 100, "platinum", T0 - dt.timedelta(days=i), 10000)

        results = compare_windows(db_session, 100, "platinum", T0, window_days_options=(7, 14, 30))

        assert set(results.keys()) == {7, 14, 30}
        assert results[7].sample_count != results[30].sample_count

    def test_does_not_write_to_market_predictability(self, db_session):
        for i in range(30):
            _insert(db_session, 100, "platinum", T0 - dt.timedelta(days=i), 40000)

        compare_windows(db_session, 100, "platinum", T0, window_days_options=(7, 14, 30))

        assert db_session.query(MarketPredictability).count() == 0

    def test_does_not_overwrite_an_existing_market_predictability_row(self, db_session):
        # A row already persisted by analyze_market() for this
        # (station_id, commodity_name, window_end) must survive a
        # compare_windows() call untouched.
        db_session.add(
            MarketPredictability(
                station_id=100, commodity_name="platinum", sample_count=99,
                window_start=T0 - dt.timedelta(days=14), window_end=T0,
                median_abs_price_change=0.01, p95_abs_price_change=0.02,
                median_abs_demand_change=0.01, p95_abs_demand_change=0.02,
                median_observation_gap_seconds=60.0, p95_observation_gap_seconds=120.0,
                volatility_class="STABLE", model_version="production-row",
            )
        )
        db_session.commit()

        compare_windows(db_session, 100, "platinum", T0, window_days_options=(7, 14, 30))

        row = db_session.query(MarketPredictability).one()
        assert row.sample_count == 99
        assert row.model_version == "production-row"


class TestDefaultReplayHorizons:
    def test_matches_freshness_curve_breakpoints(self):
        assert DEFAULT_REPLAY_HORIZONS[0] == FRESHNESS_FULL_THRESHOLD
        assert DEFAULT_REPLAY_HORIZONS[-1] == FRESHNESS_FLOOR_THRESHOLD
