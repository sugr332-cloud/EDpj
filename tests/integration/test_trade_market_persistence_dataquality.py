from __future__ import annotations

import datetime as dt

from app.backtest.trade_market_persistence import compute_data_quality_report
from app.db.models.market import MarketHistoricalObservation

T0 = dt.datetime(2026, 8, 20, 12, 0, tzinfo=dt.timezone.utc)


def _obs(session, station_id: int, commodity_name: str, sell_price: int, observed_at: dt.datetime):
    session.add(
        MarketHistoricalObservation(
            station_id=station_id, commodity_name=commodity_name, sell_price=sell_price, demand=100,
            observed_at=observed_at,
        )
    )
    session.commit()


class TestComputeDataQualityReport:
    def test_empty_dataset(self, db_session):
        report = compute_data_quality_report(db_session)
        assert report.total_observations == 0
        assert report.unique_series_count == 0
        assert report.median_observation_gap is None
        assert report.observation_period_start is None

    def test_counts_and_period(self, db_session):
        _obs(db_session, 100, "platinum", 1000, T0)
        _obs(db_session, 100, "platinum", 1000, T0 + dt.timedelta(hours=1))
        _obs(db_session, 200, "gold", 500, T0 + dt.timedelta(hours=2))

        report = compute_data_quality_report(db_session)

        assert report.total_observations == 3
        assert report.unique_series_count == 2
        assert report.observation_period_start == T0.replace(tzinfo=None)
        assert report.observation_period_end == (T0 + dt.timedelta(hours=2)).replace(tzinfo=None)

    def test_median_observation_gap_within_a_series(self, db_session):
        _obs(db_session, 100, "platinum", 1000, T0)
        _obs(db_session, 100, "platinum", 1000, T0 + dt.timedelta(minutes=10))
        _obs(db_session, 100, "platinum", 1000, T0 + dt.timedelta(minutes=40))

        report = compute_data_quality_report(db_session)

        # gaps: 10min, 30min -> median 20min
        assert report.median_observation_gap == dt.timedelta(minutes=20)

    def test_series_with_only_one_observation_contributes_no_gap(self, db_session):
        _obs(db_session, 100, "platinum", 1000, T0)
        report = compute_data_quality_report(db_session)
        assert report.median_observation_gap is None
