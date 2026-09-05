from __future__ import annotations

import datetime as dt

from app.backtest.evaluation_run import (
    EvaluationTarget,
    MAX_EVALUATION_TARGETS,
    decide_freshness_adoption,
    decide_volatility_adoption,
    run_evaluation,
    select_evaluation_targets,
)
from app.backtest.freshness_evaluation import FreshnessBucketStats, FreshnessMonotonicityResult
from app.backtest.volatility_evaluation import ClassForecastErrorStats, OrderingHypothesisResult
from app.db.models.journal import JournalEvent
from app.db.models.market import MarketPredictability, MarketSnapshot
from app.db.models.timing import TimingSample
from app.journal import events as ev
from tests.integration.test_eddn_archive import FakeStreamingHttpClient, _archive_url, _compress_day, _envelope

NOW = dt.datetime(2026, 8, 20, 12, 0, tzinfo=dt.timezone.utc)


def _volatility_result(
    ordering_holds: bool | None, stable_within: bool | None = None, volatile_exceeds: bool | None = None
) -> OrderingHypothesisResult:
    return OrderingHypothesisResult(
        class_stats={},
        ordering_holds=ordering_holds,
        stable_within_mae_threshold=stable_within,
        volatile_exceeds_mae_threshold=volatile_exceeds,
    )


def _freshness_result(overall_monotonic: bool | None) -> FreshnessMonotonicityResult:
    return FreshnessMonotonicityResult(bucket_stats={}, pairwise_non_decreasing={}, overall_monotonic=overall_monotonic)


class TestDecideVolatilityAdoption:
    def test_go_when_ordering_holds_and_both_thresholds_satisfied(self):
        result = _volatility_result(ordering_holds=True, stable_within=True, volatile_exceeds=True)
        assert decide_volatility_adoption(result) == "GO"

    def test_conditional_go_when_ordering_holds_but_a_threshold_check_fails(self):
        result = _volatility_result(ordering_holds=True, stable_within=False, volatile_exceeds=True)
        assert decide_volatility_adoption(result) == "CONDITIONAL_GO"

    def test_no_go_when_ordering_does_not_hold(self):
        # This is the reviewer's "must not rubber-stamp the current
        # config" check: even though ordering_holds came from
        # classify()'s CURRENT thresholds, a broken ordering must map to
        # NO_GO, never GO.
        result = _volatility_result(ordering_holds=False)
        assert decide_volatility_adoption(result) == "NO_GO"

    def test_insufficient_when_ordering_holds_is_none(self):
        result = _volatility_result(ordering_holds=None)
        assert decide_volatility_adoption(result) == "INSUFFICIENT"

    def test_signature_has_no_parameter_for_current_thresholds(self):
        import inspect

        params = list(inspect.signature(decide_volatility_adoption).parameters)
        assert params == ["result"]


class TestDecideFreshnessAdoption:
    def test_go_when_overall_monotonic_true(self):
        assert decide_freshness_adoption(_freshness_result(True)) == "GO"

    def test_no_go_when_overall_monotonic_false(self):
        # Same non-rubber-stamping guarantee for the freshness axis.
        assert decide_freshness_adoption(_freshness_result(False)) == "NO_GO"

    def test_insufficient_when_overall_monotonic_none(self):
        assert decide_freshness_adoption(_freshness_result(None)) == "INSUFFICIENT"

    def test_signature_has_no_parameter_for_current_thresholds(self):
        import inspect

        params = list(inspect.signature(decide_freshness_adoption).parameters)
        assert params == ["result"]


class TestSelectEvaluationTargets:
    def _snapshot(self, session, station_id, commodity_name, source, observed_at):
        session.add(
            MarketSnapshot(
                station_id=station_id, commodity_name=commodity_name, buy_price=100, sell_price=110,
                supply=50, demand=50, observed_at=observed_at, source=source,
            )
        )
        session.commit()

    def test_excludes_eddn_sourced_rows(self, db_session):
        self._snapshot(db_session, 100, "platinum", "eddn", NOW)
        self._snapshot(db_session, 200, "gold", "journal", NOW)

        targets = select_evaluation_targets(db_session)

        assert targets == [EvaluationTarget(station_id=200, commodity_name="gold")]

    def test_orders_by_observation_count_descending(self, db_session):
        for i in range(3):
            self._snapshot(db_session, 100, "platinum", "journal", NOW - dt.timedelta(hours=i))
        self._snapshot(db_session, 200, "gold", "journal", NOW)

        targets = select_evaluation_targets(db_session)

        assert targets[0] == EvaluationTarget(station_id=100, commodity_name="platinum")

    def test_limits_to_max_targets(self, db_session):
        for station_id in range(300):
            self._snapshot(db_session, station_id, "platinum", "journal", NOW)

        targets = select_evaluation_targets(db_session, max_targets=5)

        assert len(targets) == 5
        assert MAX_EVALUATION_TARGETS == 20


def _build_payloads(now: dt.datetime, window_days: int) -> dict[str, bytes]:
    """Station 100/platinum swings wildly day to day (volatile); station
    200/gold stays flat (stable)."""
    window_start = now - dt.timedelta(days=window_days)
    dates = [(window_start + dt.timedelta(days=i)).date() for i in range((now.date() - window_start.date()).days + 1)]
    volatile_prices = [40000, 90000, 20000, 80000]
    stable_prices = [9000]
    payloads = {}
    for i, date in enumerate(dates):
        ts = f"{date:%Y-%m-%d}T12:00:00Z"
        envelopes = [
            _envelope(100, ts, [{"name": "platinum", "sellPrice": volatile_prices[i % len(volatile_prices)], "demand": 100}]),
            _envelope(200, ts, [{"name": "gold", "sellPrice": stable_prices[i % len(stable_prices)], "demand": 100}]),
        ]
        payloads[_archive_url(date)] = _compress_day(envelopes)
    return payloads


class TestRunEvaluation:
    def test_report_covers_every_target_and_window(self, db_session):
        targets = [
            EvaluationTarget(station_id=100, commodity_name="platinum"),
            EvaluationTarget(station_id=200, commodity_name="gold"),
        ]
        client = FakeStreamingHttpClient(_build_payloads(NOW, window_days=3))

        report = run_evaluation(
            db_session, client, NOW, targets, window_days_options=(1, 2, 3), t0_interval=dt.timedelta(hours=6)
        )

        assert report.targets == targets
        assert set(report.target_sample_counts.keys()) == set(targets)
        assert set(report.volatility_by_window.keys()) == {1, 2, 3}
        assert set(report.volatility_decision_by_window.keys()) == {1, 2, 3}
        assert report.freshness is not None
        assert report.freshness_decision in ("GO", "CONDITIONAL_GO", "NO_GO", "INSUFFICIENT")
        assert report.journal_coverage is not None

    def test_never_writes_to_market_predictability(self, db_session):
        targets = [EvaluationTarget(station_id=100, commodity_name="platinum")]
        client = FakeStreamingHttpClient(_build_payloads(NOW, window_days=2))

        run_evaluation(db_session, client, NOW, targets, window_days_options=(1, 2), t0_interval=dt.timedelta(hours=6))

        assert db_session.query(MarketPredictability).count() == 0

    def test_journal_coverage_reflects_timing_samples(self, db_session):
        db_session.add(
            JournalEvent(
                file_name="Journal.1.log", line_number=1, event_type=ev.DOCKED, timestamp=NOW - dt.timedelta(hours=1),
                payload={"MarketID": 100, "StationName": "Farseer Inc", "StarSystem": "Deciat", "SystemAddress": 1},
            )
        )
        db_session.add(
            TimingSample(
                segment_type="jump", start_file_name="Journal.1.log", start_line_number=1,
                end_file_name="Journal.1.log", end_line_number=2,
                start_time=NOW - dt.timedelta(minutes=30), end_time=NOW - dt.timedelta(minutes=29),
                duration_seconds=60.0, reached_known_target=True,
            )
        )
        db_session.commit()

        client = FakeStreamingHttpClient({})
        report = run_evaluation(db_session, client, NOW, targets=[], window_days_options=(1,), t0_interval=dt.timedelta(hours=6))

        assert report.journal_coverage.state_reconstruction_coverage == 1.0  # DOCKED event precedes the TimingSample
        assert "jump" in report.journal_coverage.diagnostics_by_segment_type
