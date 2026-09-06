from __future__ import annotations

import datetime as dt

from app.market.price_plausibility import (
    CommodityAnomalyDetail,
    CommodityPriceStats,
    CrossStationPatternInfo,
    PersistenceInfo,
    PriceAnomalyAssessment,
    SellObservation,
    StationAnomalyProfile,
    assess_station,
    classify,
    compute_commodity_stats,
    compute_cross_station_patterns,
    compute_global_medians,
    compute_persistence,
    compute_station_anomaly_profile,
    compute_station_median_ratio,
    dedupe_latest,
    refine_with_cross_station_pattern,
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

    def test_value_difference_absolute_is_price_minus_global_median(self):
        # §19.5/§20 (Feature B v3): the raw credit gap, independent of
        # ratio -- lets a caller tell "2x ratio on an 80cr commodity"
        # (economically trivial) apart from "2x ratio on a 45,000cr
        # commodity" (economically huge) even though both score
        # value_ratio=2.0.
        deduped = {
            (1, "hydrogenfuel"): SellObservation(1, "hydrogenfuel", 160, 10, T0),
            (2, "gold"): SellObservation(2, "gold", 90000, 10, T0),
        }
        global_median = {"hydrogenfuel": 80, "gold": 45000}
        result = compute_commodity_stats(deduped, global_median)
        assert result[(1, "hydrogenfuel")].value_ratio == 2.0
        assert result[(1, "hydrogenfuel")].value_difference_absolute == 80
        assert result[(2, "gold")].value_ratio == 2.0
        assert result[(2, "gold")].value_difference_absolute == 45000

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
        stats = CommodityPriceStats(percentile=1.0, value_ratio=2.0, value_difference_absolute=45000, max_tie_count=1, max_tie_share=0.02, observation_count=50)
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
        stats = CommodityPriceStats(percentile=1.0, value_ratio=1.4, value_difference_absolute=1200, max_tie_count=143, max_tie_share=0.0298, observation_count=4796)
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
        stats = CommodityPriceStats(percentile=1.0, value_ratio=1.05, value_difference_absolute=2250, max_tie_count=1, max_tie_share=0.001, observation_count=1000)
        assessment = PriceAnomalyAssessment(
            station_id=1, station_median_ratio=1.0, worst_commodity_name="water",
            worst_commodity_stats=stats, n_reference_commodities=1,
        )
        label = classify(
            assessment, station_ratio_threshold=1.3, commodity_percentile_threshold=0.99,
            commodity_max_tie_share_threshold=0.05, commodity_value_ratio_threshold=1.3,
        )
        assert label == "NORMAL"


class TestClassifyAbsoluteFloorV3:
    """Feature B v3 (§19.5/§20): value_ratio alone is purely
    multiplicative and flags economically trivial swings on cheap
    commodities -- the real hydrogenfuel case (global median 80cr,
    ~80-100cr absolute difference already scores a 2x ratio). These
    tests use the actual real-data shapes found in §19.4: hydrogenfuel
    (small absolute gap) vs. gold/Heck Silo (large absolute gap), both
    at value_ratio~1.4-2.0, to confirm the floor separates them."""

    def _hydrogenfuel_like_stats(self):
        # real §19.4 shape: median=80, station price ~164 (2.05x ratio,
        # only 84cr absolute difference)
        return CommodityPriceStats(
            percentile=0.9933, value_ratio=2.05, value_difference_absolute=84,
            max_tie_count=32, max_tie_share=0.0067, observation_count=5758,
        )

    def _heck_silo_gold_like_stats(self):
        # real §16.3/§18.2 shape: median=47663, station price=67793
        # (1.42x ratio, 20130cr absolute difference)
        return CommodityPriceStats(
            percentile=1.0, value_ratio=1.422, value_difference_absolute=20130,
            max_tie_count=1, max_tie_share=0.0002, observation_count=5467,
        )

    def test_without_floor_both_cases_flagged_identically(self):
        # this is the §19.5 problem: without an absolute floor, a
        # trivial hydrogenfuel swing and a genuinely large gold swing
        # are indistinguishable once value_ratio clears the same bar.
        hydrogenfuel = PriceAnomalyAssessment(
            station_id=1, station_median_ratio=1.0, worst_commodity_name="hydrogenfuel",
            worst_commodity_stats=self._hydrogenfuel_like_stats(), n_reference_commodities=1,
        )
        gold = PriceAnomalyAssessment(
            station_id=2, station_median_ratio=1.0, worst_commodity_name="gold",
            worst_commodity_stats=self._heck_silo_gold_like_stats(), n_reference_commodities=1,
        )
        kwargs = dict(station_ratio_threshold=1.3, commodity_percentile_threshold=0.99,
                      commodity_max_tie_share_threshold=0.05, commodity_value_ratio_threshold=1.3)
        assert classify(hydrogenfuel, **kwargs) == "COMMODITY_ANOMALY"
        assert classify(gold, **kwargs) == "COMMODITY_ANOMALY"

    def test_with_floor_hydrogenfuel_excluded_gold_still_flagged(self):
        # a floor of e.g. 5000cr should exclude the economically trivial
        # hydrogenfuel case while still catching the genuinely large
        # gold swing.
        hydrogenfuel = PriceAnomalyAssessment(
            station_id=1, station_median_ratio=1.0, worst_commodity_name="hydrogenfuel",
            worst_commodity_stats=self._hydrogenfuel_like_stats(), n_reference_commodities=1,
        )
        gold = PriceAnomalyAssessment(
            station_id=2, station_median_ratio=1.0, worst_commodity_name="gold",
            worst_commodity_stats=self._heck_silo_gold_like_stats(), n_reference_commodities=1,
        )
        kwargs = dict(station_ratio_threshold=1.3, commodity_percentile_threshold=0.99,
                      commodity_max_tie_share_threshold=0.05, commodity_value_ratio_threshold=1.3,
                      commodity_absolute_floor=5000)
        assert classify(hydrogenfuel, **kwargs) == "NORMAL"
        assert classify(gold, **kwargs) == "COMMODITY_ANOMALY"

    def test_floor_none_is_backward_compatible_default(self):
        # omitting commodity_absolute_floor must behave exactly as
        # before its introduction (no floor check).
        gold = PriceAnomalyAssessment(
            station_id=2, station_median_ratio=1.0, worst_commodity_name="gold",
            worst_commodity_stats=self._heck_silo_gold_like_stats(), n_reference_commodities=1,
        )
        kwargs = dict(station_ratio_threshold=1.3, commodity_percentile_threshold=0.99,
                      commodity_max_tie_share_threshold=0.05, commodity_value_ratio_threshold=1.3)
        assert classify(gold, **kwargs) == classify(gold, commodity_absolute_floor=None, **kwargs)


class TestComputePersistence:
    """§19/§22: persistence is diagnostic metadata ONLY -- these tests
    verify the bookkeeping (anomaly_days/observed_days/ratio), not any
    classification behavior, since compute_persistence() is never
    called from classify() and must stay that way."""

    def test_flagged_every_observed_day_gives_ratio_one(self):
        daily_anomalies = [{1}, {1}, {1}]
        daily_observed = [{1, 2}, {1, 2}, {1, 2}]

        result = compute_persistence(daily_anomalies, daily_observed)

        assert result[1] == PersistenceInfo(station_id=1, anomaly_days=3, observed_days=3, persistence_ratio=1.0)

    def test_flagged_once_out_of_several_observed_days(self):
        daily_anomalies = [{1}, set(), set()]
        daily_observed = [{1, 2}, {1, 2}, {1, 2}]

        result = compute_persistence(daily_anomalies, daily_observed)

        assert result[1].anomaly_days == 1
        assert result[1].observed_days == 3
        assert result[1].persistence_ratio == 1 / 3

    def test_ratio_is_relative_to_days_actually_observed_not_total_days(self):
        # station 1 is only OBSERVED on 2 of 5 days, flagged both times
        # -- persistence_ratio must be 1.0 (2/2), not 2/5.
        daily_anomalies = [{1}, set(), {1}, set(), set()]
        daily_observed = [{1}, {2}, {1}, {2}, {2}]

        result = compute_persistence(daily_anomalies, daily_observed)

        assert result[1].anomaly_days == 2
        assert result[1].observed_days == 2
        assert result[1].persistence_ratio == 1.0

    def test_never_flagged_station_is_absent_from_result(self):
        daily_anomalies = [set(), set()]
        daily_observed = [{1, 2}, {1, 2}]

        result = compute_persistence(daily_anomalies, daily_observed)

        assert 2 not in result

    def test_mismatched_list_lengths_raise(self):
        import pytest
        with pytest.raises(ValueError):
            compute_persistence([{1}], [{1}, {2}])

    def test_inconsistent_input_raises_rather_than_silently_dividing_by_zero(self):
        # station flagged anomalous on a day it's missing from the
        # "observed" set for that same day -- a caller bug, must not
        # be silently swallowed as persistence_ratio=undefined.
        import pytest
        daily_anomalies = [{1}]
        daily_observed = [set()]  # station 1 wasn't in the observed set that day
        with pytest.raises(ValueError):
            compute_persistence(daily_anomalies, daily_observed)


class TestComputeStationAnomalyProfile:
    """Feature B v4 (§23): distinguishes Heck Silo's shape (1 unrelated
    commodity spikes) from the real mining-hotspot shape (§22's
    transient-candidate finding: several related high-value minerals
    elevated together) -- diagnostic only, not consumed by classify()."""

    BASELINE = {"gold": 45000, "silver": 33000, "platinum": 59000, "painite": 55000, "osmium": 47000, "tritium": 53000}
    KWARGS = dict(commodity_percentile_threshold=0.99, commodity_max_tie_share_threshold=0.05,
                  commodity_value_ratio_threshold=1.3)

    def _build_population(self, heck_silo_station: int, hotspot_station: int):
        deduped = {}
        # 150 background stations per commodity: two special stations
        # (Heck-Silo-like and hotspot-like) share "gold" in this fixture,
        # so whichever of them is second-highest still needs percentile
        # >=0.99 -- with n background stations that requires
        # (n+1)/(n+2)>=0.99, i.e. n>=98; 150 gives comfortable margin.
        # Also keeps tie_share for a lone outlier (1/152 ~= 0.7%) well
        # under a 5% threshold.
        for commodity, base in self.BASELINE.items():
            for i in range(150):
                deduped[(100 + i, commodity)] = SellObservation(100 + i, commodity, base + i * 3, 10, T0)

        # Heck-Silo-like station: ONLY gold spikes, everything else normal.
        deduped[(heck_silo_station, "gold")] = SellObservation(heck_silo_station, "gold", 250000, 10, T0)
        for commodity in ["silver", "platinum", "painite", "osmium", "tritium"]:
            deduped[(heck_silo_station, commodity)] = SellObservation(heck_silo_station, commodity, self.BASELINE[commodity], 10, T0)

        # mining-hotspot-like station: ALL related minerals elevated together
        for commodity, base in self.BASELINE.items():
            deduped[(hotspot_station, commodity)] = SellObservation(hotspot_station, commodity, int(base * 2.2), 10, T0)

        global_median = compute_global_medians({k: v for k, v in deduped.items() if k[0] >= 100})
        return deduped, global_median

    def test_heck_silo_shape_has_low_anomalous_commodity_count(self):
        deduped, global_median = self._build_population(heck_silo_station=1, hotspot_station=2)
        commodity_stats = compute_commodity_stats(deduped, global_median)

        profile = compute_station_anomaly_profile(1, deduped, commodity_stats, **self.KWARGS)

        assert profile.anomalous_commodity_count == 1
        assert profile.anomalous_commodities[0].commodity_name == "gold"

    def test_mining_hotspot_shape_has_high_anomalous_commodity_count(self):
        deduped, global_median = self._build_population(heck_silo_station=1, hotspot_station=2)
        commodity_stats = compute_commodity_stats(deduped, global_median)

        profile = compute_station_anomaly_profile(2, deduped, commodity_stats, **self.KWARGS)

        assert profile.anomalous_commodity_count == len(self.BASELINE)  # all 6 elevated together

    def test_heck_silo_shape_has_high_value_concentration(self):
        # one commodity accounts for ~all of the "anomaly budget"
        deduped, global_median = self._build_population(heck_silo_station=1, hotspot_station=2)
        commodity_stats = compute_commodity_stats(deduped, global_median)

        profile = compute_station_anomaly_profile(1, deduped, commodity_stats, **self.KWARGS)

        assert profile.anomaly_value_concentration == 1.0  # only one anomalous commodity at all

    def test_mining_hotspot_shape_has_lower_value_concentration(self):
        # the anomaly "budget" is spread across several commodities, not
        # dominated by a single one
        deduped, global_median = self._build_population(heck_silo_station=1, hotspot_station=2)
        commodity_stats = compute_commodity_stats(deduped, global_median)

        profile = compute_station_anomaly_profile(2, deduped, commodity_stats, **self.KWARGS)

        assert profile.anomaly_value_concentration < 0.5

    def test_no_anomalous_commodities_gives_none_concentration(self):
        deduped = {(1, "gold"): SellObservation(1, "gold", 45000, 10, T0)}
        global_median = {"gold": 45000}
        commodity_stats = compute_commodity_stats(deduped, global_median)

        profile = compute_station_anomaly_profile(1, deduped, commodity_stats, **self.KWARGS)

        assert profile.anomalous_commodity_count == 0
        assert profile.anomaly_value_concentration is None

    def test_absolute_floor_is_respected_in_group_profile(self):
        # same floor mechanism as classify() -- a cheap-commodity
        # trivial swing must not count toward anomalous_commodity_count.
        deduped, global_median = self._build_population(heck_silo_station=1, hotspot_station=2)
        commodity_stats = compute_commodity_stats(deduped, global_median)

        profile = compute_station_anomaly_profile(
            1, deduped, commodity_stats, commodity_absolute_floor=999999999, **self.KWARGS
        )
        # no realistic absolute gap clears an intentionally absurd floor
        assert profile.anomalous_commodity_count == 0


def _stats(ratio: float) -> CommodityPriceStats:
    return CommodityPriceStats(percentile=1.0, value_ratio=ratio, value_difference_absolute=ratio * 10000,
                                max_tie_count=1, max_tie_share=0.01, observation_count=100)


def _profile(station_id: int, commodities_and_ratios: dict[str, float]) -> StationAnomalyProfile:
    details = tuple(CommodityAnomalyDetail(name, _stats(ratio)) for name, ratio in commodities_and_ratios.items())
    total = sum(d.stats.value_difference_absolute for d in details)
    concentration = max(d.stats.value_difference_absolute for d in details) / total if details and total else None
    return StationAnomalyProfile(
        station_id=station_id, anomalous_commodities=details,
        anomalous_commodity_count=len(details), anomaly_value_concentration=concentration,
    )


class TestComputeCrossStationPatterns:
    """§24, Feature B v5: does an anomalous commodity combination
    reproduce across independent stations (evidence of a real shared
    market condition), or is it seen at only one station (unconfirmed
    either way)?"""

    def test_isolated_pattern_has_count_one_and_no_similarity(self):
        # Heck-Silo-shaped: a pattern nobody else shares.
        profiles = {1: _profile(1, {"gold": 1.42, "palladium": 1.32})}

        result = compute_cross_station_patterns(profiles)

        assert result[1].pattern_station_count == 1
        assert result[1].pattern_price_similarity is None
        assert result[1].commodity_pattern == frozenset({"gold", "palladium"})

    def test_shared_pattern_with_near_identical_ratios_has_low_similarity(self):
        # the real §23 finding: multiple stations share the exact same
        # 4-commodity combination at nearly identical ratios.
        profiles = {
            1: _profile(1, {"cobalt": 4.22, "osmium": 5.73, "painite": 3.84, "platinum": 5.10}),
            2: _profile(2, {"cobalt": 4.21, "osmium": 5.73, "painite": 3.84, "platinum": 5.09}),
            3: _profile(3, {"cobalt": 4.22, "osmium": 5.72, "painite": 3.85, "platinum": 5.10}),
        }

        result = compute_cross_station_patterns(profiles)

        assert result[1].pattern_station_count == 3
        assert result[1].pattern_price_similarity < 0.01  # tightly clustered
        assert result[1].commodity_pattern == frozenset({"cobalt", "osmium", "painite", "platinum"})

    def test_shared_pattern_with_divergent_ratios_has_higher_similarity_value(self):
        # same commodity SET shared, but the actual ratios differ a lot
        # -- weaker evidence of one shared real condition.
        profiles = {
            1: _profile(1, {"gold": 1.4, "silver": 1.5}),
            2: _profile(2, {"gold": 3.0, "silver": 4.0}),
        }

        result = compute_cross_station_patterns(profiles)

        assert result[1].pattern_station_count == 2
        assert result[1].pattern_price_similarity > 0.2

    def test_different_commodity_sets_are_different_patterns_even_with_overlap(self):
        # {gold} alone is a DIFFERENT pattern from {gold, palladium} --
        # a subset match must not be conflated with an exact match.
        profiles = {
            1: _profile(1, {"gold": 1.42}),
            2: _profile(2, {"gold": 1.42, "palladium": 1.32}),
        }

        result = compute_cross_station_patterns(profiles)

        assert result[1].pattern_station_count == 1
        assert result[2].pattern_station_count == 1
        assert result[1].commodity_pattern != result[2].commodity_pattern

    def test_station_with_no_anomalous_commodities_is_absent_from_result(self):
        profiles = {1: _profile(1, {}), 2: _profile(2, {"gold": 1.42})}

        result = compute_cross_station_patterns(profiles)

        assert 1 not in result
        assert 2 in result


class TestRefineWithCrossStationPattern:
    """§25, Provisional Threshold Calibration: combines classify()'s
    verdict with Feature B v5's cross-station corroboration. Only ever
    touches COMMODITY_ANOMALY/STRONG_ANOMALY -- never claims
    "confirmed corruption," only distinguishes "explained by a repeated
    real market condition" from "not yet explained.\""""

    def test_non_anomalous_labels_pass_through_unchanged(self):
        assert refine_with_cross_station_pattern("NORMAL", None, shared_pattern_min_stations=2) == "NORMAL"
        assert refine_with_cross_station_pattern("STATION_ANOMALY", None, shared_pattern_min_stations=2) == "STATION_ANOMALY"

    def test_no_pattern_info_is_suspicious(self):
        assert refine_with_cross_station_pattern("COMMODITY_ANOMALY", None, shared_pattern_min_stations=2) == "SUSPICIOUS"

    def test_pattern_shared_by_enough_stations_is_known_market_pattern(self):
        pattern = CrossStationPatternInfo(
            station_id=1, commodity_pattern=frozenset({"cobalt", "osmium", "painite", "platinum"}),
            pattern_station_count=6, pattern_price_similarity=0.00004,
        )
        assert refine_with_cross_station_pattern("COMMODITY_ANOMALY", pattern, shared_pattern_min_stations=2) == "KNOWN_MARKET_PATTERN"

    def test_pattern_below_threshold_stays_suspicious(self):
        pattern = CrossStationPatternInfo(
            station_id=1, commodity_pattern=frozenset({"steel"}), pattern_station_count=1, pattern_price_similarity=None,
        )
        assert refine_with_cross_station_pattern("COMMODITY_ANOMALY", pattern, shared_pattern_min_stations=2) == "SUSPICIOUS"

    def test_strong_anomaly_also_refined(self):
        pattern = CrossStationPatternInfo(
            station_id=1, commodity_pattern=frozenset({"gold"}), pattern_station_count=1, pattern_price_similarity=None,
        )
        assert refine_with_cross_station_pattern("STRONG_ANOMALY", pattern, shared_pattern_min_stations=2) == "SUSPICIOUS"


class TestKnownSuspiciousReferences:
    """§24.3/§25: fixed regression cases using the REAL numbers found
    for W8Y-WVM and Heck Silo on 2026-09-05. These are explicitly
    "Known Suspicious References," never "Known Positive"/"Confirmed
    Corruption" -- no external ground truth confirmed either as
    genuine data corruption. Any future change to classify(),
    compute_station_anomaly_profile(), or compute_cross_station_patterns()
    must keep both of these SUSPICIOUS (not silently reclassified as
    KNOWN_MARKET_PATTERN or NORMAL) unless a deliberate, documented
    design change explains why."""

    BASE_KWARGS = dict(station_ratio_threshold=1.3, commodity_percentile_threshold=0.99,
                        commodity_max_tie_share_threshold=0.01, commodity_value_ratio_threshold=1.3,
                        commodity_absolute_floor=15000)

    def test_w8y_wvm_steel_case_remains_suspicious(self):
        # real shape: 20 commodities, only steel elevated (~5x, ~19,210cr
        # absolute gap), nothing else remarkable -- §24.3.
        stats = CommodityPriceStats(percentile=0.999, value_ratio=4.99, value_difference_absolute=19210,
                                     max_tie_count=1, max_tie_share=0.001, observation_count=800)
        assessment = PriceAnomalyAssessment(
            station_id=3707315456, station_median_ratio=1.05, worst_commodity_name="steel",
            worst_commodity_stats=stats, n_reference_commodities=1,
        )
        label = classify(assessment, **self.BASE_KWARGS)
        pattern_info = CrossStationPatternInfo(
            station_id=3707315456, commodity_pattern=frozenset({"steel"}),
            pattern_station_count=1, pattern_price_similarity=None,
        )
        assert refine_with_cross_station_pattern(label, pattern_info, shared_pattern_min_stations=2) == "SUSPICIOUS"

    def test_heck_silo_gold_palladium_case_remains_suspicious(self):
        # real shape: gold ratio=1.42/diff=20130, palladium ratio=1.32/
        # diff=17390, station_median_ratio=1.073 (normal) -- §16.3/§23.2.
        stats = CommodityPriceStats(percentile=1.0, value_ratio=1.42, value_difference_absolute=20130,
                                     max_tie_count=1, max_tie_share=0.0002, observation_count=5467)
        assessment = PriceAnomalyAssessment(
            station_id=4223685123, station_median_ratio=1.073, worst_commodity_name="gold",
            worst_commodity_stats=stats, n_reference_commodities=25,
        )
        label = classify(assessment, **self.BASE_KWARGS)
        pattern_info = CrossStationPatternInfo(
            station_id=4223685123, commodity_pattern=frozenset({"gold", "palladium"}),
            pattern_station_count=1, pattern_price_similarity=None,
        )
        assert refine_with_cross_station_pattern(label, pattern_info, shared_pattern_min_stations=2) == "SUSPICIOUS"

    def test_known_market_pattern_group_is_not_suspicious(self):
        # real shape: cobalt/osmium/painite/platinum, 6 stations,
        # near-identical ratios -- §24.2, contrast case.
        stats = CommodityPriceStats(percentile=1.0, value_ratio=5.10, value_difference_absolute=243467,
                                     max_tie_count=1, max_tie_share=0.0002, observation_count=800)
        assessment = PriceAnomalyAssessment(
            station_id=4338552835, station_median_ratio=1.15, worst_commodity_name="platinum",
            worst_commodity_stats=stats, n_reference_commodities=4,
        )
        label = classify(assessment, **self.BASE_KWARGS)
        pattern_info = CrossStationPatternInfo(
            station_id=4338552835, commodity_pattern=frozenset({"cobalt", "osmium", "painite", "platinum"}),
            pattern_station_count=6, pattern_price_similarity=0.00004,
        )
        assert refine_with_cross_station_pattern(label, pattern_info, shared_pattern_min_stations=2) == "KNOWN_MARKET_PATTERN"
