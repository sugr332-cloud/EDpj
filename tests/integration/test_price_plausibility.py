from __future__ import annotations

import datetime as dt

from app.market.price_plausibility import (
    CommodityPriceStats,
    PriceAnomalyAssessment,
    SellObservation,
    assess_station,
    classify,
    compute_commodity_stats,
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


class TestComputeCommodityStats:
    def test_highest_price_in_population_gets_percentile_one(self):
        deduped = {
            (1, "gold"): SellObservation(1, "gold", 40000, 10, T0),
            (2, "gold"): SellObservation(2, "gold", 45000, 10, T0),
            (3, "gold"): SellObservation(3, "gold", 90000, 10, T0),  # the max
        }
        global_median = {"gold": 45000}
        result = compute_commodity_stats(deduped, global_median)
        assert result[(3, "gold")].percentile == 1.0

    def test_lowest_price_gets_low_percentile(self):
        deduped = {
            (1, "gold"): SellObservation(1, "gold", 40000, 10, T0),
            (2, "gold"): SellObservation(2, "gold", 45000, 10, T0),
            (3, "gold"): SellObservation(3, "gold", 90000, 10, T0),
        }
        global_median = {"gold": 45000}
        result = compute_commodity_stats(deduped, global_median)
        assert result[(1, "gold")].percentile < result[(2, "gold")].percentile < result[(3, "gold")].percentile

    def test_percentiles_are_per_commodity_independent(self):
        deduped = {
            (1, "gold"): SellObservation(1, "gold", 90000, 10, T0),   # max for gold
            (1, "silver"): SellObservation(1, "silver", 1, 10, T0),   # min for silver
            (2, "silver"): SellObservation(2, "silver", 99999, 10, T0),
        }
        global_median = {"gold": 45000, "silver": 50000}
        result = compute_commodity_stats(deduped, global_median)
        assert result[(1, "gold")].percentile == 1.0
        assert result[(1, "silver")].percentile < result[(2, "silver")].percentile

    def test_value_ratio_is_price_over_global_median(self):
        deduped = {(1, "gold"): SellObservation(1, "gold", 90000, 10, T0)}
        global_median = {"gold": 45000}
        result = compute_commodity_stats(deduped, global_median)
        assert result[(1, "gold")].value_ratio == 2.0

    def test_isolated_max_has_small_tie_count_and_share(self):
        # regression fixture matching the real gold/Heck Silo shape:
        # exactly ONE station at the population max.
        deduped = {
            (1, "gold"): SellObservation(1, "gold", 90000, 10, T0),  # the lone max
            (2, "gold"): SellObservation(2, "gold", 45000, 10, T0),
            (3, "gold"): SellObservation(3, "gold", 44000, 10, T0),
            (4, "gold"): SellObservation(4, "gold", 46000, 10, T0),
        }
        global_median = {"gold": 45000}
        result = compute_commodity_stats(deduped, global_median)
        stats = result[(1, "gold")]
        assert stats.max_tie_count == 1
        assert stats.max_tie_share == 0.25
        assert stats.observation_count == 4

    def test_shared_market_ceiling_regression_case(self):
        """Fixed regression test (§17.3): the real 2026-09-05 gallite
        finding -- 143 of 4,796 stations (2.98%) independently reported
        the EXACT SAME maximum price. That is a common, legitimate price
        ceiling, not an anomaly, even though every one of those 143
        stations scores percentile=1.0 (same as a genuinely isolated
        outlier like gold/Heck Silo). This test uses a scaled-down but
        structurally identical shape (many stations tied at the max
        among a larger normal population) -- any future change to
        compute_commodity_stats/classify must keep such a station OUT
        of COMMODITY_ANOMALY via a tight max_tie_share threshold, even
        though its raw percentile alone would suggest otherwise."""
        deduped = {}
        # 20 "normal" stations spread across a realistic price range
        for i, price in enumerate(range(2000, 4000, 100), start=100):
            deduped[(i, "gallite")] = SellObservation(i, "gallite", price, 10, T0)
        # 5 independent stations all tied at the natural ceiling (4000)
        for i in range(200, 205):
            deduped[(i, "gallite")] = SellObservation(i, "gallite", 4000, 10, T0)
        global_median = {"gallite": 2950}

        result = compute_commodity_stats(deduped, global_median)
        tied_station_stats = result[(200, "gallite")]

        assert tied_station_stats.percentile == 1.0  # naive rank alone looks maximally suspicious
        assert tied_station_stats.max_tie_count == 5
        assert tied_station_stats.max_tie_share == 5 / 25  # 20% -- NOT rare

        # classify() must NOT flag this as COMMODITY_ANOMALY under a
        # reasonable tie-share threshold, even at percentile=1.0.
        assessment = PriceAnomalyAssessment(
            station_id=200, station_median_ratio=1.0, worst_commodity_name="gallite",
            worst_commodity_stats=tied_station_stats, n_reference_commodities=1,
        )
        label = classify(
            assessment, station_ratio_threshold=1.3, commodity_percentile_threshold=0.99,
            commodity_max_tie_share_threshold=0.05, commodity_value_ratio_threshold=1.3,
        )
        assert label == "NORMAL"


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
            (1, "gold"): SellObservation(1, "gold", 90000, 10, T0),  # extreme, isolated outlier
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
        # widen the gold population so max_tie_share is meaningful (a
        # lone outlier among only 5 stations would trivially be 20% --
        # real populations are thousands of stations, per §16-17).
        for i, price in enumerate(range(44000, 46000, 100), start=1000):
            deduped[(i, "gold")] = SellObservation(i, "gold", price, 10, T0)
        global_median = {"aluminium": 3090, "steel": 4820, "gold": 45500}
        return deduped, global_median

    def test_station_normal_but_one_commodity_extreme_is_commodity_anomaly(self):
        deduped, global_median = self._deduped_heck_silo_like()
        ratios = compute_station_median_ratio(deduped, global_median, min_reference_commodities=2)
        stats = compute_commodity_stats(deduped, global_median)

        assessment = assess_station(1, deduped, ratios, stats)

        assert assessment.station_median_ratio < 1.2  # aluminium/steel are normal, median stays low
        assert assessment.worst_commodity_name == "gold"
        assert assessment.worst_commodity_stats.percentile == 1.0
        assert assessment.worst_commodity_stats.max_tie_count == 1  # isolated, not a shared ceiling

        label = classify(
            assessment, station_ratio_threshold=1.3, commodity_percentile_threshold=0.99,
            commodity_max_tie_share_threshold=0.05, commodity_value_ratio_threshold=1.3,
        )
        assert label == "COMMODITY_ANOMALY"

    def test_fully_normal_station_is_normal(self):
        deduped, global_median = self._deduped_heck_silo_like()
        ratios = compute_station_median_ratio(deduped, global_median, min_reference_commodities=2)
        stats = compute_commodity_stats(deduped, global_median)

        assessment = assess_station(2, deduped, ratios, stats)
        label = classify(
            assessment, station_ratio_threshold=1.3, commodity_percentile_threshold=0.99,
            commodity_max_tie_share_threshold=0.05, commodity_value_ratio_threshold=1.3,
        )

        assert label == "NORMAL"

    def test_both_axes_anomalous_is_strong_anomaly(self):
        stats = CommodityPriceStats(percentile=1.0, value_ratio=2.0, max_tie_count=1, max_tie_share=0.02, observation_count=50)
        assessment = PriceAnomalyAssessment(
            station_id=99, station_median_ratio=2.5, worst_commodity_name="tritium",
            worst_commodity_stats=stats, n_reference_commodities=5,
        )
        label = classify(
            assessment, station_ratio_threshold=1.3, commodity_percentile_threshold=0.99,
            commodity_max_tie_share_threshold=0.05, commodity_value_ratio_threshold=1.3,
        )
        assert label == "STRONG_ANOMALY"

    def test_missing_station_level_data_does_not_crash_classification(self):
        # e.g. J8V-06B's real case: below min_reference_commodities, so
        # station_median_ratio is None -- must not be treated as anomalous.
        assessment = PriceAnomalyAssessment(
            station_id=99, station_median_ratio=None, worst_commodity_name=None,
            worst_commodity_stats=None, n_reference_commodities=1,
        )
        label = classify(
            assessment, station_ratio_threshold=1.3, commodity_percentile_threshold=0.99,
            commodity_max_tie_share_threshold=0.05, commodity_value_ratio_threshold=1.3,
        )
        assert label == "NORMAL"

    def test_high_percentile_but_common_ceiling_is_not_commodity_anomaly(self):
        # percentile=1.0 AND value_ratio high, but max_tie_share is large
        # (a common ceiling, per §17.3) -- must not be flagged.
        stats = CommodityPriceStats(percentile=1.0, value_ratio=1.4, max_tie_count=143, max_tie_share=0.0298, observation_count=4796)
        assessment = PriceAnomalyAssessment(
            station_id=1, station_median_ratio=1.0, worst_commodity_name="gallite",
            worst_commodity_stats=stats, n_reference_commodities=1,
        )
        label = classify(
            assessment, station_ratio_threshold=1.3, commodity_percentile_threshold=0.99,
            commodity_max_tie_share_threshold=0.01, commodity_value_ratio_threshold=1.3,
        )
        assert label == "NORMAL"

    def test_high_percentile_isolated_but_small_magnitude_is_not_commodity_anomaly(self):
        # percentile=1.0 AND isolated (tie_share tiny), but value_ratio
        # barely above the population median -- not a large enough
        # magnitude to call it anomalous on its own.
        stats = CommodityPriceStats(percentile=1.0, value_ratio=1.05, max_tie_count=1, max_tie_share=0.001, observation_count=1000)
        assessment = PriceAnomalyAssessment(
            station_id=1, station_median_ratio=1.0, worst_commodity_name="water",
            worst_commodity_stats=stats, n_reference_commodities=1,
        )
        label = classify(
            assessment, station_ratio_threshold=1.3, commodity_percentile_threshold=0.99,
            commodity_max_tie_share_threshold=0.05, commodity_value_ratio_threshold=1.3,
        )
        assert label == "NORMAL"
