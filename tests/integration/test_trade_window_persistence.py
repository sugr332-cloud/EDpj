from __future__ import annotations

import datetime as dt

from app.backtest.trade_market_persistence import (
    PersistenceMeasurementStatus,
    _material_decrease_within_window,
    _rows_by_station_commodity,
    collect_price_comparisons,
    compute_margin_change_decomposition,
    compute_profit_window_stats,
    compute_window_price_stats,
)
from app.db.models.market import MarketHistoricalObservation

T0 = dt.datetime(2026, 8, 20, 12, 0, tzinfo=dt.timezone.utc)


def _obs(session, station_id, commodity_name, sell_price, observed_at, demand=100, buy_price=None):
    session.add(
        MarketHistoricalObservation(
            station_id=station_id, commodity_name=commodity_name, sell_price=sell_price, demand=demand,
            buy_price=buy_price, observed_at=observed_at,
        )
    )
    session.commit()


class TestWindowRelativeTolerance:
    def test_worked_example_from_the_spec_is_accepted(self, db_session):
        # T0=12:00, window=30min, target=12:30, observation at 12:31 -> valid (gap=1min).
        _obs(db_session, 100, "platinum", 1000, T0)
        _obs(db_session, 100, "platinum", 1000, T0 + dt.timedelta(minutes=31))
        stats = compute_window_price_stats(db_session, dt.timedelta(minutes=30))
        assert stats.comparison_count == 1

    def test_worked_example_from_the_spec_is_rejected(self, db_session):
        # T0=12:00, window=30min, target=12:30, observation at 15:00 -> rejected
        # (150min away, exceeds the 30min tolerance) -- this is exactly the
        # methodological flaw 2-6F-T1's flat 6h MAX_OBSERVATION_GAP had.
        # (both rows are their own T0 candidate -- eligible_count=2 -- and
        # neither finds a valid match: the first because 15:00 is too far
        # from its 12:30 target, the second because it's the series' last
        # observation with nothing after it at all.)
        _obs(db_session, 100, "platinum", 1000, T0)
        _obs(db_session, 100, "platinum", 1000, T0 + dt.timedelta(hours=3))
        stats = compute_window_price_stats(db_session, dt.timedelta(minutes=30))
        assert stats.comparison_count == 0
        assert stats.censored_count == 2

    def test_tolerance_scales_with_window_not_a_flat_constant(self, db_session):
        # A 5-minute window's tolerance is 5 minutes, NOT 6 hours -- an
        # observation 15 minutes later (3x the window) must be rejected.
        _obs(db_session, 100, "platinum", 1000, T0)
        _obs(db_session, 100, "platinum", 1000, T0 + dt.timedelta(minutes=15))
        stats = compute_window_price_stats(db_session, dt.timedelta(minutes=5))
        assert stats.comparison_count == 0

    def test_boundary_at_exactly_the_tolerance_is_accepted(self, db_session):
        _obs(db_session, 100, "platinum", 1000, T0)
        _obs(db_session, 100, "platinum", 1000, T0 + dt.timedelta(minutes=60))  # exactly 2x window = boundary
        stats = compute_window_price_stats(db_session, dt.timedelta(minutes=30))
        assert stats.comparison_count == 1

    def test_nearest_candidate_is_chosen_when_multiple_are_in_range(self, db_session):
        # Isolate a single T0's own match via collect_price_comparisons
        # directly (the full aggregate would also count the 25-minute row
        # as its own separate T0 candidate, which isn't what this test is
        # about).
        _obs(db_session, 100, "platinum", 1000, T0)
        _obs(db_session, 100, "platinum", 900, T0 + dt.timedelta(minutes=25))
        _obs(db_session, 100, "platinum", 800, T0 + dt.timedelta(minutes=31))
        comparisons, _, _ = collect_price_comparisons(db_session, dt.timedelta(minutes=30))
        # nearest to target(12:30) is 12:31 (1 min) vs 12:25 (5 min) -> price 800 wins
        t0_comparison = next(c for c in comparisons if c.t0_price == 1000)
        assert t0_comparison.matched_price == 800


class TestUnchangedVsMaterialDecrease:
    def test_unchanged_rate_uses_symmetric_band(self, db_session):
        _obs(db_session, 100, "platinum", 1000, T0)
        _obs(db_session, 100, "platinum", 1030, T0 + dt.timedelta(minutes=30))  # +3%, within symmetric 5% band
        stats = compute_window_price_stats(db_session, dt.timedelta(minutes=30))
        assert stats.unchanged_rate == 1.0
        assert stats.decrease_rate == 0.0  # it went UP, not down

    def test_decrease_rate_counts_any_drop_not_just_material(self, db_session):
        _obs(db_session, 100, "platinum", 1000, T0)
        _obs(db_session, 100, "platinum", 990, T0 + dt.timedelta(minutes=30))  # -1%, not material
        stats = compute_window_price_stats(db_session, dt.timedelta(minutes=30))
        assert stats.decrease_rate == 1.0
        assert stats.material_decrease_at_window_rate == 0.0

    def test_material_decrease_at_window_requires_the_threshold(self, db_session):
        _obs(db_session, 100, "platinum", 1000, T0)
        _obs(db_session, 100, "platinum", 940, T0 + dt.timedelta(minutes=30))  # -6%, material
        stats = compute_window_price_stats(db_session, dt.timedelta(minutes=30))
        assert stats.material_decrease_at_window_rate == 1.0


class TestAtWindowVsWithinWindow:
    def test_dip_and_recovery_counts_within_but_not_at_window(self, db_session):
        _obs(db_session, 100, "platinum", 1000, T0)
        _obs(db_session, 100, "platinum", 900, T0 + dt.timedelta(minutes=15))  # -10%, material, mid-window
        _obs(db_session, 100, "platinum", 1000, T0 + dt.timedelta(minutes=30))  # recovered by window end

        stats = compute_window_price_stats(db_session, dt.timedelta(minutes=30))
        # Isolate just T0's own within-window scan directly -- the full
        # aggregate also treats the 15-minute row as its own separate T0
        # candidate (whose own forward window shows a price *increase*,
        # diluting the rate), which isn't what this test is about.
        rows = _rows_by_station_commodity(db_session)[(100, "platinum")]
        within_t0 = _material_decrease_within_window(rows, 0, dt.timedelta(minutes=30), 0.05)

        assert stats.material_decrease_at_window_rate == 0.0  # the T0+30min snapshot shows no drop
        assert within_t0 is True  # but a drop DID happen inside the window, from T0's own perspective


class TestObservationGapReporting:
    def test_comparison_gap_is_recorded_and_summarized(self, db_session):
        _obs(db_session, 100, "platinum", 1000, T0)
        _obs(db_session, 100, "platinum", 1000, T0 + dt.timedelta(minutes=32))  # 2min late vs 30min target
        stats = compute_window_price_stats(db_session, dt.timedelta(minutes=30))
        assert stats.median_observation_gap == dt.timedelta(minutes=2)


class TestProfitWindowStats:
    def test_insufficient_when_no_buy_price(self, db_session):
        _obs(db_session, 100, "platinum", 1000, T0)
        stats = compute_profit_window_stats(db_session, dt.timedelta(minutes=30))
        assert stats.status == PersistenceMeasurementStatus.INSUFFICIENT

    def test_records_source_dest_time_diff(self, db_session):
        _obs(db_session, 100, "platinum", sell_price=500, buy_price=1000, observed_at=T0)
        _obs(db_session, 200, "platinum", sell_price=1500, observed_at=T0 + dt.timedelta(minutes=5))
        _obs(db_session, 100, "platinum", sell_price=500, buy_price=1000, observed_at=T0 + dt.timedelta(minutes=30))
        _obs(db_session, 200, "platinum", sell_price=1500, observed_at=T0 + dt.timedelta(minutes=32))

        stats = compute_profit_window_stats(db_session, dt.timedelta(minutes=30))

        assert stats.status == PersistenceMeasurementStatus.COMPUTED
        assert stats.median_source_dest_time_diff == dt.timedelta(minutes=5)
        assert stats.profit_condition_persistence == 1.0


class TestMarginChangeDecomposition:
    def test_insufficient_when_no_buy_price(self, db_session):
        _obs(db_session, 100, "platinum", 1000, T0)
        result = compute_margin_change_decomposition(db_session, dt.timedelta(minutes=30))
        assert result.status == PersistenceMeasurementStatus.INSUFFICIENT

    def test_classifies_buy_only_change(self, db_session):
        # Two source (buy) observations x two dest (sell) observations,
        # both within alignment tolerance of each other, means every
        # combination is its own eligible T0 route-snapshot (same
        # combinatorial nature already established for
        # compute_profit_condition_persistence's own tests) -- here every
        # combination happens to match "buy changed, sell didn't" or
        # "neither changed" (comparing a later row against itself when it
        # is both the dest and its own later-match).
        _obs(db_session, 100, "platinum", sell_price=500, buy_price=1000, observed_at=T0)
        _obs(db_session, 200, "platinum", sell_price=1500, observed_at=T0)
        _obs(db_session, 100, "platinum", sell_price=500, buy_price=1100, observed_at=T0 + dt.timedelta(minutes=30))
        _obs(db_session, 200, "platinum", sell_price=1500, observed_at=T0 + dt.timedelta(minutes=30))

        result = compute_margin_change_decomposition(db_session, dt.timedelta(minutes=30))

        assert result.status == PersistenceMeasurementStatus.COMPUTED
        assert result.source_buy_only_changed_count == 2
        assert result.dest_sell_only_changed_count == 0
        assert result.both_changed_count == 0
        assert result.neither_changed_count == 2

    def test_classifies_both_changed(self, db_session):
        _obs(db_session, 100, "platinum", sell_price=500, buy_price=1000, observed_at=T0)
        _obs(db_session, 200, "platinum", sell_price=1500, observed_at=T0)
        _obs(db_session, 100, "platinum", sell_price=500, buy_price=1100, observed_at=T0 + dt.timedelta(minutes=30))
        _obs(db_session, 200, "platinum", sell_price=1600, observed_at=T0 + dt.timedelta(minutes=30))

        result = compute_margin_change_decomposition(db_session, dt.timedelta(minutes=30))

        assert result.both_changed_count == 1
