from __future__ import annotations

import datetime as dt

from app.backtest.trade_market_persistence import (
    PersistenceMeasurementStatus,
    ReversionOutcome,
    collect_material_decrease_events,
    compute_buy_side_movement_status,
    compute_demand_change_at_events,
    compute_price_reversion,
    summarize_events_by_commodity,
    summarize_events_by_station,
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


def _one_event(session):
    _obs(session, 100, "platinum", 1000, T0, demand=50)
    _obs(session, 100, "platinum", 900, T0 + dt.timedelta(minutes=20), demand=40)
    events, censored = collect_material_decrease_events(session)
    return events, censored


class TestGroupSummaries:
    def test_commodity_with_no_events_is_absent(self, db_session):
        _obs(db_session, 100, "platinum", 1000, T0)
        _obs(db_session, 100, "platinum", 1000, T0 + dt.timedelta(minutes=20))
        events, _ = collect_material_decrease_events(db_session)
        assert summarize_events_by_commodity(events) == {}

    def test_summarizes_by_commodity(self, db_session):
        events, _ = _one_event(db_session)
        summary = summarize_events_by_commodity(events)
        assert summary["platinum"].event_count == 1
        assert summary["platinum"].median_relative_decrease == 0.1
        assert summary["platinum"].median_time_to_event == dt.timedelta(minutes=20)

    def test_summarizes_by_station(self, db_session):
        events, _ = _one_event(db_session)
        summary = summarize_events_by_station(events)
        assert summary[100].event_count == 1


class TestDemandCorrelation:
    def test_demand_decreased_alongside_price(self, db_session):
        events, _ = _one_event(db_session)
        result = compute_demand_change_at_events(events)
        assert result.event_count == 1
        assert result.demand_decreased_count == 1
        assert result.demand_increased_count == 0
        assert result.demand_unchanged_count == 0

    def test_demand_unchanged_is_counted_separately(self, db_session):
        _obs(db_session, 100, "platinum", 1000, T0, demand=50)
        _obs(db_session, 100, "platinum", 900, T0 + dt.timedelta(minutes=20), demand=50)
        events, _ = collect_material_decrease_events(db_session)
        result = compute_demand_change_at_events(events)
        assert result.demand_unchanged_count == 1


class TestPriceReversion:
    def test_recovers_to_95_percent_counts_as_reverted(self, db_session):
        _obs(db_session, 100, "platinum", 1000, T0)
        _obs(db_session, 100, "platinum", 900, T0 + dt.timedelta(minutes=20))  # the event
        _obs(db_session, 100, "platinum", 950, T0 + dt.timedelta(minutes=40))  # 95% of 1000 -> reverted

        events, _ = collect_material_decrease_events(db_session)
        cases = compute_price_reversion(db_session, events, reversion_window=dt.timedelta(hours=1))

        assert cases[0].outcome == ReversionOutcome.REVERTED
        assert cases[0].time_to_reversion == dt.timedelta(minutes=20)

    def test_later_observation_below_recovery_threshold_is_persisted(self, db_session):
        _obs(db_session, 100, "platinum", 1000, T0)
        _obs(db_session, 100, "platinum", 900, T0 + dt.timedelta(minutes=20))
        _obs(db_session, 100, "platinum", 920, T0 + dt.timedelta(minutes=40))  # below 950 recovery target

        events, _ = collect_material_decrease_events(db_session)
        cases = compute_price_reversion(db_session, events, reversion_window=dt.timedelta(hours=1))

        assert cases[0].outcome == ReversionOutcome.PERSISTED
        assert cases[0].time_to_reversion is None

    def test_no_later_observation_at_all_is_censored_not_persisted(self, db_session):
        events, _ = _one_event(db_session)
        cases = compute_price_reversion(db_session, events, reversion_window=dt.timedelta(hours=1))
        assert cases[0].outcome == ReversionOutcome.CENSORED

    def test_observation_beyond_the_reversion_window_never_leaks_in(self, db_session):
        _obs(db_session, 100, "platinum", 1000, T0)
        _obs(db_session, 100, "platinum", 900, T0 + dt.timedelta(minutes=20))
        _obs(db_session, 100, "platinum", 1000, T0 + dt.timedelta(hours=2))  # would revert, but outside window

        events, _ = collect_material_decrease_events(db_session)
        cases = compute_price_reversion(db_session, events, reversion_window=dt.timedelta(hours=1))

        assert cases[0].outcome == ReversionOutcome.CENSORED


class TestBuySideMovementStatus:
    def test_insufficient_when_no_row_has_buy_price(self, db_session):
        _obs(db_session, 100, "platinum", 1000, T0)
        assert compute_buy_side_movement_status(db_session) == PersistenceMeasurementStatus.INSUFFICIENT

    def test_computed_when_a_row_has_buy_price(self, db_session):
        _obs(db_session, 100, "platinum", 1000, T0, buy_price=900)
        assert compute_buy_side_movement_status(db_session) == PersistenceMeasurementStatus.COMPUTED
