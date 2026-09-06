from __future__ import annotations

import datetime as dt

from app.backtest.trade_market_persistence import (
    PersistenceMeasurementStatus,
    compute_price_persistence,
    compute_profit_condition_persistence,
    compute_time_to_first_material_decrease,
)
from app.db.models.market import MarketHistoricalObservation

T0 = dt.datetime(2026, 8, 20, 12, 0, tzinfo=dt.timezone.utc)


def _obs(session, station_id: int, commodity_name: str, sell_price: int, observed_at: dt.datetime, buy_price: int | None = None):
    session.add(
        MarketHistoricalObservation(
            station_id=station_id, commodity_name=commodity_name, sell_price=sell_price, demand=100,
            buy_price=buy_price, observed_at=observed_at,
        )
    )
    session.commit()


class TestPricePersistence:
    def test_no_comparison_available_is_excluded_not_zero(self, db_session):
        _obs(db_session, 100, "platinum", 1000, T0)
        result = compute_price_persistence(db_session, dt.timedelta(minutes=15))
        assert result.eligible_count == 1
        assert result.comparison_count == 0
        assert result.price_persistence is None

    def test_unchanged_price_counts_as_persisted(self, db_session):
        _obs(db_session, 100, "platinum", 1000, T0)
        _obs(db_session, 100, "platinum", 1000, T0 + dt.timedelta(minutes=15))
        result = compute_price_persistence(db_session, dt.timedelta(minutes=15))
        assert result.comparison_count == 1
        assert result.material_decrease_count == 0
        assert result.price_persistence == 1.0

    def test_material_decrease_at_exactly_five_percent_counts_as_decrease(self, db_session):
        _obs(db_session, 100, "platinum", 1000, T0)
        _obs(db_session, 100, "platinum", 950, T0 + dt.timedelta(minutes=15))  # exactly -5%
        result = compute_price_persistence(db_session, dt.timedelta(minutes=15))
        assert result.material_decrease_count == 1
        assert result.price_persistence == 0.0

    def test_decrease_just_below_threshold_does_not_count(self, db_session):
        _obs(db_session, 100, "platinum", 1000, T0)
        _obs(db_session, 100, "platinum", 951, T0 + dt.timedelta(minutes=15))  # -4.9%
        result = compute_price_persistence(db_session, dt.timedelta(minutes=15))
        assert result.material_decrease_count == 0
        assert result.price_persistence == 1.0

    def test_price_increase_never_counts_as_material_decrease(self, db_session):
        _obs(db_session, 100, "platinum", 1000, T0)
        _obs(db_session, 100, "platinum", 2000, T0 + dt.timedelta(minutes=15))
        result = compute_price_persistence(db_session, dt.timedelta(minutes=15))
        assert result.material_decrease_count == 0

    def test_observation_outside_gap_tolerance_is_excluded(self, db_session):
        _obs(db_session, 100, "platinum", 1000, T0)
        _obs(db_session, 100, "platinum", 1, T0 + dt.timedelta(minutes=15) + dt.timedelta(hours=6, minutes=1))
        result = compute_price_persistence(db_session, dt.timedelta(minutes=15))
        assert result.comparison_count == 0

    def test_zero_baseline_price_is_excluded_not_counted_as_no_decrease(self, db_session):
        _obs(db_session, 100, "platinum", 0, T0)
        _obs(db_session, 100, "platinum", 100, T0 + dt.timedelta(minutes=15))
        result = compute_price_persistence(db_session, dt.timedelta(minutes=15))
        assert result.comparison_count == 0
        assert result.undefined_baseline_count == 1

    def test_different_station_commodity_pairs_never_mixed(self, db_session):
        _obs(db_session, 100, "platinum", 1000, T0)
        _obs(db_session, 200, "platinum", 1, T0 + dt.timedelta(minutes=15))  # different station, huge drop
        result = compute_price_persistence(db_session, dt.timedelta(minutes=15))
        # station 100's T0 has no comparison of its own (no later obs at station 100),
        # station 200's single point has no T0 predecessor to compare from either.
        assert result.eligible_count == 2
        assert result.comparison_count == 0

    def test_future_observations_never_leak_into_an_earlier_t0(self, db_session):
        # observed_at ordering must not let a later row be treated as its own T0's past.
        _obs(db_session, 100, "platinum", 1000, T0)
        _obs(db_session, 100, "platinum", 500, T0 + dt.timedelta(minutes=10))
        result = compute_price_persistence(db_session, dt.timedelta(minutes=30))
        # T0's window(30min) target lands past the only later observation (10min) plus max_gap tolerance
        # is generous, so it IS a valid comparison for T0 -- but the second row (T0+10) must not itself
        # get compared against something before it.
        assert result.eligible_count == 2


class TestTimeToFirstMaterialDecrease:
    def test_decrease_found_is_not_censored(self, db_session):
        _obs(db_session, 100, "platinum", 1000, T0)
        _obs(db_session, 100, "platinum", 900, T0 + dt.timedelta(minutes=20))
        summary = compute_time_to_first_material_decrease(db_session)
        assert summary.event_count == 1
        assert summary.censored_count == 0
        assert summary.median_time_to_first_decrease == dt.timedelta(minutes=20)

    def test_no_decrease_ever_is_right_censored_not_indefinite_stability(self, db_session):
        _obs(db_session, 100, "platinum", 1000, T0)
        _obs(db_session, 100, "platinum", 1000, T0 + dt.timedelta(minutes=20))
        _obs(db_session, 100, "platinum", 990, T0 + dt.timedelta(minutes=40))
        summary = compute_time_to_first_material_decrease(db_session)
        assert summary.event_count == 0
        assert summary.censored_count == 2  # T0 at 0min and T0 at 20min both never see a decrease
        assert summary.median_time_to_first_decrease is None

    def test_only_the_first_qualifying_decrease_is_used_not_a_later_larger_one(self, db_session):
        _obs(db_session, 100, "platinum", 1000, T0)
        _obs(db_session, 100, "platinum", 940, T0 + dt.timedelta(minutes=10))  # first material decrease
        _obs(db_session, 100, "platinum", 100, T0 + dt.timedelta(minutes=50))  # bigger, but not first
        summary = compute_time_to_first_material_decrease(db_session)
        assert summary.cases[0].time_to_event == dt.timedelta(minutes=10)

    def test_t0_with_no_later_observation_at_all_is_excluded(self, db_session):
        _obs(db_session, 100, "platinum", 1000, T0)
        summary = compute_time_to_first_material_decrease(db_session)
        assert summary.cases == []


class TestProfitConditionPersistence:
    def test_insufficient_when_no_row_has_buy_price(self, db_session):
        _obs(db_session, 100, "platinum", 1000, T0)
        result = compute_profit_condition_persistence(db_session, dt.timedelta(minutes=15))
        assert result.status == PersistenceMeasurementStatus.INSUFFICIENT
        assert result.persistence is None

    def test_computed_when_a_profitable_route_persists(self, db_session):
        _obs(db_session, 100, "platinum", sell_price=500, buy_price=1000, observed_at=T0)  # source: buy 1000
        _obs(db_session, 200, "platinum", sell_price=1500, observed_at=T0)  # dest: sell 1500 -> profit=500
        _obs(db_session, 100, "platinum", sell_price=500, buy_price=1000, observed_at=T0 + dt.timedelta(minutes=15))
        _obs(db_session, 200, "platinum", sell_price=1500, observed_at=T0 + dt.timedelta(minutes=15))

        result = compute_profit_condition_persistence(db_session, dt.timedelta(minutes=15))

        # 2 source observations x 2 dest observations, all mutually within
        # max_gap of each other, so every combination is its own eligible
        # T0 route-snapshot (eligible_count=4) -- only the one anchored at
        # the earliest source (T0) has a later match within this window.
        assert result.status == PersistenceMeasurementStatus.COMPUTED
        assert result.eligible_count == 4
        assert result.comparison_count == 1
        assert result.persistence == 1.0

    def test_route_invalidated_when_spread_turns_non_positive_later(self, db_session):
        _obs(db_session, 100, "platinum", sell_price=500, buy_price=1000, observed_at=T0)
        _obs(db_session, 200, "platinum", sell_price=1500, observed_at=T0)
        _obs(db_session, 100, "platinum", sell_price=500, buy_price=1600, observed_at=T0 + dt.timedelta(minutes=15))
        _obs(db_session, 200, "platinum", sell_price=1500, observed_at=T0 + dt.timedelta(minutes=15))

        result = compute_profit_condition_persistence(db_session, dt.timedelta(minutes=15))

        assert result.comparison_count == 1
        assert result.persistence == 0.0

    def test_same_station_is_never_treated_as_its_own_trade_route(self, db_session):
        _obs(db_session, 100, "platinum", sell_price=1500, buy_price=1000, observed_at=T0)
        result = compute_profit_condition_persistence(db_session, dt.timedelta(minutes=15))
        assert result.eligible_count == 0
