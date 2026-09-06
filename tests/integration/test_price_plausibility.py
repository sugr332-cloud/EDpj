from __future__ import annotations

import datetime as dt

from app.market.price_plausibility import (
    SellObservation,
    compute_global_medians,
    compute_station_median_ratio,
    dedupe_latest,
)

T0 = dt.datetime(2026, 9, 5, 0, 0, tzinfo=dt.timezone.utc)
T1 = dt.datetime(2026, 9, 5, 12, 0, tzinfo=dt.timezone.utc)


class TestDedupeLatest:
    def test_keeps_only_latest_per_station_commodity(self):
        observations = [
            SellObservation(station_id=1, commodity_name="gold", sell_price=45000, demand=10, observed_at=T0),
            SellObservation(station_id=1, commodity_name="gold", sell_price=46000, demand=12, observed_at=T1),
        ]
        result = dedupe_latest(observations)
        assert len(result) == 1
        assert result[(1, "gold")].sell_price == 46000

    def test_different_stations_and_commodities_all_kept(self):
        observations = [
            SellObservation(station_id=1, commodity_name="gold", sell_price=45000, demand=10, observed_at=T0),
            SellObservation(station_id=2, commodity_name="gold", sell_price=44000, demand=10, observed_at=T0),
            SellObservation(station_id=1, commodity_name="silver", sell_price=30000, demand=10, observed_at=T0),
        ]
        result = dedupe_latest(observations)
        assert len(result) == 3

    def test_repeated_broadcast_of_identical_price_collapses_to_one(self):
        # T4-B's real finding: same-day duplicate broadcasts of an
        # unchanged price -- must not inflate per-station counts.
        observations = [
            SellObservation(station_id=1, commodity_name="gold", sell_price=45000, demand=10, observed_at=T0),
            SellObservation(station_id=1, commodity_name="gold", sell_price=45000, demand=10, observed_at=T1),
        ]
        result = dedupe_latest(observations)
        assert len(result) == 1


class TestComputeGlobalMedians:
    def test_computes_median_per_commodity(self):
        deduped = {
            (1, "gold"): SellObservation(1, "gold", 40000, 10, T0),
            (2, "gold"): SellObservation(2, "gold", 46000, 10, T0),
            (3, "gold"): SellObservation(3, "gold", 45000, 10, T0),
        }
        result = compute_global_medians(deduped)
        assert result["gold"] == 45000


class TestComputeStationMedianRatio:
    def test_station_with_multiple_reference_commodities_gets_median_ratio(self):
        deduped = {
            (1, "gold"): SellObservation(1, "gold", 90000, 10, T0),   # 2x global median
            (1, "silver"): SellObservation(1, "silver", 60000, 10, T0),  # 2x global median
        }
        global_median = {"gold": 45000, "silver": 30000}

        result = compute_station_median_ratio(deduped, global_median)

        assert result[1] == 2.0

    def test_station_below_min_reference_commodities_excluded(self):
        deduped = {(1, "gold"): SellObservation(1, "gold", 90000, 10, T0)}
        global_median = {"gold": 45000}

        result = compute_station_median_ratio(deduped, global_median, min_reference_commodities=2)

        assert 1 not in result

    def test_commodity_not_in_global_median_is_skipped_not_erroring(self):
        deduped = {
            (1, "gold"): SellObservation(1, "gold", 90000, 10, T0),
            (1, "unknowncommodity"): SellObservation(1, "unknowncommodity", 1000, 10, T0),
            (1, "silver"): SellObservation(1, "silver", 60000, 10, T0),
        }
        global_median = {"gold": 45000, "silver": 30000}

        result = compute_station_median_ratio(deduped, global_median, min_reference_commodities=2)

        assert result[1] == 2.0  # unknowncommodity contributes nothing, still 2 valid reference commodities

    def test_realistic_normal_station_ratio_near_one(self):
        deduped = {
            (1, "gold"): SellObservation(1, "gold", 45100, 10, T0),
            (1, "silver"): SellObservation(1, "silver", 29900, 10, T0),
        }
        global_median = {"gold": 45000, "silver": 30000}

        result = compute_station_median_ratio(deduped, global_median)

        assert 0.99 < result[1] < 1.01
