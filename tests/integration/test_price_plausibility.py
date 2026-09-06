from __future__ import annotations

import datetime as dt

from app.market.price_plausibility import (
    PriceAnomalyAssessment,
    SellObservation,
    assess_station,
    classify,
    compute_commodity_percentiles,
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


class TestComputeCommodityPercentiles:
    def test_highest_price_in_population_gets_percentile_one(self):
        deduped = {
            (1, "gold"): SellObservation(1, "gold", 40000, 10, T0),
            (2, "gold"): SellObservation(2, "gold", 45000, 10, T0),
            (3, "gold"): SellObservation(3, "gold", 90000, 10, T0),  # the max
        }
        result = compute_commodity_percentiles(deduped)
        assert result[(3, "gold")] == 1.0

    def test_lowest_price_gets_low_percentile(self):
        deduped = {
            (1, "gold"): SellObservation(1, "gold", 40000, 10, T0),
            (2, "gold"): SellObservation(2, "gold", 45000, 10, T0),
            (3, "gold"): SellObservation(3, "gold", 90000, 10, T0),
        }
        result = compute_commodity_percentiles(deduped)
        assert result[(1, "gold")] < result[(2, "gold")] < result[(3, "gold")]

    def test_percentiles_are_per_commodity_independent(self):
        deduped = {
            (1, "gold"): SellObservation(1, "gold", 90000, 10, T0),   # max for gold
            (1, "silver"): SellObservation(1, "silver", 1, 10, T0),   # min for silver
            (2, "silver"): SellObservation(2, "silver", 99999, 10, T0),
        }
        result = compute_commodity_percentiles(deduped)
        assert result[(1, "gold")] == 1.0
        assert result[(1, "silver")] < result[(2, "silver")]


class TestAssessStationAndClassify:
    def _deduped_heck_silo_like(self):
        # station 1: aluminium/steel land mid-pack among several
        # background stations, but gold is the population's absolute
        # max -- the exact real-data pattern found in §16.3. A wider
        # background population (not just 1 comparison station) is
        # needed for "percentile" to be meaningful at all.
        deduped = {
            (1, "aluminium"): SellObservation(1, "aluminium", 3090, 10, T0),
            (1, "steel"): SellObservation(1, "steel", 4820, 10, T0),
            (1, "gold"): SellObservation(1, "gold", 90000, 10, T0),  # extreme outlier
            (2, "aluminium"): SellObservation(2, "aluminium", 3073, 10, T0),
            (2, "steel"): SellObservation(2, "steel", 4813, 10, T0),
            (2, "gold"): SellObservation(2, "gold", 45000, 10, T0),
            (3, "aluminium"): SellObservation(3, "aluminium", 3120, 10, T0),
            (3, "steel"): SellObservation(3, "steel", 4850, 10, T0),
            (3, "gold"): SellObservation(3, "gold", 44500, 10, T0),
            (4, "aluminium"): SellObservation(4, "aluminium", 3050, 10, T0),
            (4, "steel"): SellObservation(4, "steel", 4790, 10, T0),
            (4, "gold"): SellObservation(4, "gold", 45500, 10, T0),
            (5, "aluminium"): SellObservation(5, "aluminium", 3200, 10, T0),
            (5, "steel"): SellObservation(5, "steel", 4900, 10, T0),
            (5, "gold"): SellObservation(5, "gold", 46000, 10, T0),
        }
        global_median = {"aluminium": 3090, "steel": 4820, "gold": 45500}
        return deduped, global_median

    def test_station_normal_but_one_commodity_extreme_is_commodity_anomaly(self):
        deduped, global_median = self._deduped_heck_silo_like()
        ratios = compute_station_median_ratio(deduped, global_median, min_reference_commodities=2)
        percentiles = compute_commodity_percentiles(deduped)

        assessment = assess_station(1, deduped, ratios, percentiles)

        assert assessment.station_median_ratio < 1.2  # aluminium/steel are normal, median stays low
        assert assessment.worst_commodity_percentile == 1.0
        assert assessment.worst_commodity_name == "gold"

        label = classify(assessment, station_ratio_threshold=1.3, commodity_percentile_threshold=0.99)
        assert label == "COMMODITY_ANOMALY"

    def test_fully_normal_station_is_normal(self):
        deduped, global_median = self._deduped_heck_silo_like()
        ratios = compute_station_median_ratio(deduped, global_median, min_reference_commodities=2)
        percentiles = compute_commodity_percentiles(deduped)

        assessment = assess_station(2, deduped, ratios, percentiles)
        label = classify(assessment, station_ratio_threshold=1.3, commodity_percentile_threshold=0.99)

        assert label == "NORMAL"

    def test_both_axes_anomalous_is_strong_anomaly(self):
        assessment = PriceAnomalyAssessment(
            station_id=99, station_median_ratio=2.5, worst_commodity_percentile=1.0,
            worst_commodity_name="tritium", n_reference_commodities=5,
        )
        label = classify(assessment, station_ratio_threshold=1.3, commodity_percentile_threshold=0.99)
        assert label == "STRONG_ANOMALY"

    def test_missing_station_level_data_does_not_crash_classification(self):
        # e.g. J8V-06B's real case: below min_reference_commodities, so
        # station_median_ratio is None -- must not be treated as anomalous.
        assessment = PriceAnomalyAssessment(
            station_id=99, station_median_ratio=None, worst_commodity_percentile=None,
            worst_commodity_name=None, n_reference_commodities=1,
        )
        label = classify(assessment, station_ratio_threshold=1.3, commodity_percentile_threshold=0.99)
        assert label == "NORMAL"
