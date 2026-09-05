from __future__ import annotations

import datetime as dt

from app.market.volatility import (
    Observation,
    demand_change_ratio,
    median_and_p95,
    pair_observations,
    price_change_ratio,
)

NOW = dt.datetime(2026, 8, 1, tzinfo=dt.timezone.utc)


def _obs(minutes: int, price: int, demand: int) -> Observation:
    return Observation(observed_at=NOW + dt.timedelta(minutes=minutes), price=price, demand=demand)


class TestPairObservations:
    def test_all_gaps_recorded_but_only_small_gaps_used_for_volatility(self):
        observations = [
            _obs(0, 100, 10),
            _obs(10, 105, 12),      # 10 min gap -- within max_gap
            _obs(500, 200, 50),     # ~8.2h gap -- exceeds max_gap
        ]
        pairs, gaps = pair_observations(observations, max_gap=dt.timedelta(hours=1))

        assert len(gaps) == 2  # every adjacent pair's gap is recorded
        assert len(pairs) == 1  # only the small-gap pair is usable for volatility
        assert pairs[0] == (observations[0], observations[1])

    def test_large_gap_is_not_interpolated_as_zero_change(self):
        observations = [_obs(0, 100, 10), _obs(600, 100, 10)]  # same price/demand, huge gap
        pairs, gaps = pair_observations(observations, max_gap=dt.timedelta(minutes=30))
        assert pairs == []  # excluded, not silently treated as "no change"
        assert gaps == [dt.timedelta(minutes=600)]


class TestPriceChangeRatio:
    def test_normal_case(self):
        assert price_change_ratio(_obs(0, 100, 0), _obs(1, 110, 0)) == 0.1

    def test_none_for_zero_previous_price(self):
        assert price_change_ratio(_obs(0, 0, 0), _obs(1, 110, 0)) is None

    def test_none_for_negative_previous_price(self):
        assert price_change_ratio(_obs(0, -5, 0), _obs(1, 110, 0)) is None


class TestDemandChangeRatio:
    def test_normal_case(self):
        assert demand_change_ratio(_obs(0, 0, 100), _obs(1, 0, 150), demand_floor=1) == 0.5

    def test_floor_prevents_division_by_zero(self):
        assert demand_change_ratio(_obs(0, 0, 0), _obs(1, 0, 5), demand_floor=1) == 5.0


class TestMedianAndP95:
    def test_empty_returns_none(self):
        assert median_and_p95([]) == (None, None)

    def test_single_value(self):
        assert median_and_p95([0.5]) == (0.5, 0.5)

    def test_multiple_values(self):
        median, p95 = median_and_p95([0.1, 0.2, 0.3, 0.4, 0.5])
        assert median == 0.3
        assert p95 >= 0.5  # tail estimate at/above the max observed value
