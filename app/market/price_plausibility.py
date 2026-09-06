"""Price Plausibility — station-level price corruption detection.

Spec (docs/PHASE_TRADE_T4_EDDN_COMMODITY_INITIAL_AUDIT_V0.1.md §13-16).
Detects stations whose reported commodity prices are systematically
inflated relative to the wider EDDN commodity/3 population -- found
during T4-D Accuracy Check to be a real, distinct failure mode from
market-structure anomalies (Colonisation Ship depots, §11): two
stations (Heck Silo, J8V-06B) passed the "normal two-way market"
structural filter but still showed nearly every high-value commodity
priced at roughly 3-5x (or, for J8V-06B, unrelated/non-marketable items
clustering near a near-constant value) the population's real price.

`station_median_ratio` = the MEDIAN, across a basket of liquid/widely-
traded reference commodities a station sells, of
(station_price / commodity_global_median). Using the median across
several commodities (not one) is deliberate: a single elevated
commodity can be a genuine rare-market condition, but several
commodities inflated together at the same station is a much stronger
corruption signal (§13.1's design rationale, validated on 4 known
examples in §13.2 with clean separation at ~P99).

Deduplication: a station's market update can appear multiple times in
one archive day (EDDN's own duplicate-broadcast rate, ~5-10%, T4-B
§9.5) -- the investigation script that first produced this feature
(price_plausibility_feature.py, not committed) accumulated every
repeated report into a station's ratio list rather than deduping,
inflating the displayed per-station commodity count (though not
distorting the computed ratio itself, since repeats carried identical
prices in the cases checked). This module fixes that: exactly one
price per (station, commodity) is kept -- the LATEST by observed_at,
matching how live Market data conventionally treats freshness (distinct
from BioObservation's chronological-integrity reason for keeping the
EARLIEST).

Persistence (design doc §19/§22): a multi-day validation (7 days
spread over 2 weeks) tested the hypothesis that a station flagged
anomalous on MORE days is a higher-confidence corruption candidate.
That hypothesis was REJECTED by real data -- the 10 stations flagged
on every single sampled day traced back to genuine, explainable
mechanics (real high-value rare-mineral buyback markets at what look
like mining hotspots, and economically trivial swings on cheap
commodities like hydrogenfuel/copper where the multiplicative ratio
is oversensitive), not to anything resembling the Heck Silo/gold
pattern. `compute_persistence()` below therefore exists PURELY as
diagnostic metadata for later manual/offline analysis -- it is
deliberately NOT consumed by `classify()` and must not be folded into
the anomaly score without new evidence overturning §19's finding.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class SellObservation:
    station_id: int
    commodity_name: str
    sell_price: int
    demand: int
    observed_at: object  # comparable (datetime); kept generic to avoid a hard dep here


def dedupe_latest(observations: list[SellObservation]) -> dict[tuple[int, str], SellObservation]:
    """Exactly one observation per (station_id, commodity_name) -- the
    one with the latest observed_at. Ties keep whichever is encountered
    last (stable, but not meaningfully different since a real tie means
    truly simultaneous duplicate broadcasts of the same fact)."""
    latest: dict[tuple[int, str], SellObservation] = {}
    for obs in observations:
        key = (obs.station_id, obs.commodity_name)
        current = latest.get(key)
        if current is None or obs.observed_at >= current.observed_at:
            latest[key] = obs
    return latest


def compute_global_medians(deduped: dict[tuple[int, str], SellObservation]) -> dict[str, float]:
    """Population median sell_price per commodity, across all deduped
    (station, commodity) observations passed in -- callers decide which
    stations/commodities to include (e.g. "normal market" stations only,
    a specific reference-commodity basket)."""
    prices_by_commodity: dict[str, list[int]] = defaultdict(list)
    for obs in deduped.values():
        prices_by_commodity[obs.commodity_name].append(obs.sell_price)
    return {name: statistics.median(prices) for name, prices in prices_by_commodity.items()}


def compute_station_median_ratio(
    deduped: dict[tuple[int, str], SellObservation],
    global_median: dict[str, float],
    min_reference_commodities: int = 2,
) -> dict[int, float]:
    """Per-station median of (station_price / commodity_global_median)
    across whichever reference commodities that station sells (that
    also appear in `global_median`). A station contributes to the
    result only if it has at least `min_reference_commodities` --
    a single commodity can't establish "the whole station is
    inflated," per §13.1's design rationale."""
    ratios_by_station: dict[int, list[float]] = defaultdict(list)
    for (station_id, commodity_name), obs in deduped.items():
        median = global_median.get(commodity_name)
        if median is None or median <= 0:
            continue
        ratios_by_station[station_id].append(obs.sell_price / median)

    return {
        station_id: statistics.median(ratios)
        for station_id, ratios in ratios_by_station.items()
        if len(ratios) >= min_reference_commodities
    }


@dataclass(frozen=True)
class CommodityPriceStats:
    """Feature B v2 (design doc §17.4, "T4-E Feature B v2") -- kept as
    separate components rather than collapsed into one score, per
    review direction. §17.3's real finding: a naive rank-only percentile
    cannot distinguish "143 stations independently reached the same
    natural price ceiling for a cheap, low-variance commodity" (gallite)
    from "exactly one station stands alone far above everyone else"
    (gold/Heck Silo) -- both score percentile=1.0. The tie-count/share
    fields exist specifically to make that distinction possible without
    fixing a threshold yet."""

    percentile: float  # rank within this commodity's own population (unchanged v1 definition)
    value_ratio: float  # station_price / commodity_global_median
    value_difference_absolute: float  # station_price - commodity_global_median, in credits
    max_tie_count: int  # how many stations (for this commodity) share the population's max price
    max_tie_share: float  # max_tie_count / observation_count
    observation_count: int  # population size for this commodity


def compute_commodity_stats(
    deduped: dict[tuple[int, str], SellObservation],
    global_median: dict[str, float],
) -> dict[tuple[int, str], CommodityPriceStats]:
    """Feature B v2: for EVERY (station, commodity) pair, computes rank
    (percentile), magnitude (value_ratio against the population median),
    and how common the commodity's own maximum price is (tie count/
    share) -- so a caller can tell "isolated genuine outlier" (gold: 1
    station at the max, 0.02% share) apart from "common market ceiling"
    (gallite: 143 stations, 2.98% share) without those two cases
    collapsing into the same percentile=1.0 value (§17.3)."""
    prices_by_commodity: dict[str, list[int]] = defaultdict(list)
    for (_, commodity_name), obs in deduped.items():
        prices_by_commodity[commodity_name].append(obs.sell_price)

    sorted_prices: dict[str, list[int]] = {}
    max_price: dict[str, int] = {}
    max_tie_count: dict[str, int] = {}
    for name, prices in prices_by_commodity.items():
        sorted_prices[name] = sorted(prices)
        max_price[name] = sorted_prices[name][-1]
        max_tie_count[name] = sum(1 for p in prices if p == max_price[name])

    stats: dict[tuple[int, str], CommodityPriceStats] = {}
    for key, obs in deduped.items():
        commodity_name = obs.commodity_name
        population = sorted_prices[commodity_name]
        n = len(population)
        if n == 0:
            continue
        median = global_median.get(commodity_name)
        if median is None or median <= 0:
            continue
        below_or_equal = sum(1 for p in population if p <= obs.sell_price)
        stats[key] = CommodityPriceStats(
            percentile=below_or_equal / n,
            value_ratio=obs.sell_price / median,
            value_difference_absolute=obs.sell_price - median,
            max_tie_count=max_tie_count[commodity_name],
            max_tie_share=max_tie_count[commodity_name] / n,
            observation_count=n,
        )
    return stats


@dataclass(frozen=True)
class PriceAnomalyAssessment:
    station_id: int
    station_median_ratio: float | None  # Feature A -- None if below min_reference_commodities
    worst_commodity_name: str | None
    worst_commodity_stats: CommodityPriceStats | None  # Feature B v2 -- full component breakdown
    n_reference_commodities: int


def assess_station(
    station_id: int,
    deduped: dict[tuple[int, str], SellObservation],
    station_median_ratio: dict[int, float],
    commodity_stats: dict[tuple[int, str], CommodityPriceStats],
) -> PriceAnomalyAssessment:
    """Assembles both features for one station. Does NOT classify --
    per the explicit design decision (§16.5) not to fix thresholds
    before more examples are gathered. "Worst" commodity is still
    selected by percentile (highest rank) -- the tie-count/value-ratio
    fields on that selected commodity are what let a caller judge
    whether the high rank is actually suspicious."""
    station_commodities = [c for (sid, c) in deduped if sid == station_id]
    worst_name, worst_stats = None, None
    for c in station_commodities:
        stats = commodity_stats.get((station_id, c))
        if stats is not None and (worst_stats is None or stats.percentile > worst_stats.percentile):
            worst_stats, worst_name = stats, c

    return PriceAnomalyAssessment(
        station_id=station_id,
        station_median_ratio=station_median_ratio.get(station_id),
        worst_commodity_name=worst_name,
        worst_commodity_stats=worst_stats,
        n_reference_commodities=len(station_commodities),
    )


def _is_commodity_anomalous(
    stats: CommodityPriceStats,
    commodity_percentile_threshold: float,
    commodity_max_tie_share_threshold: float,
    commodity_value_ratio_threshold: float,
    commodity_absolute_floor: float | None,
) -> bool:
    """Shared per-commodity conjunction (§17.3/§17.4, extended by §20's
    optional floor) -- used by both classify() (on the single "worst"
    commodity) and compute_station_anomaly_profile() (on EVERY reference
    commodity a station sells, per §23's group-structure design)."""
    anomalous = (
        stats.percentile >= commodity_percentile_threshold
        and stats.max_tie_share <= commodity_max_tie_share_threshold
        and stats.value_ratio >= commodity_value_ratio_threshold
    )
    if anomalous and commodity_absolute_floor is not None:
        anomalous = stats.value_difference_absolute >= commodity_absolute_floor
    return anomalous


def classify(
    assessment: PriceAnomalyAssessment,
    station_ratio_threshold: float,
    commodity_percentile_threshold: float,
    commodity_max_tie_share_threshold: float,
    commodity_value_ratio_threshold: float,
    commodity_absolute_floor: float | None = None,
) -> str:
    """Two-axis classification (design doc §16-19, "T4-E"). Thresholds
    are caller-supplied, never hardcoded here -- production values
    remain UNRESOLVED per §14/§16.5/§17.4/§19.6/§20 pending more
    calibration examples.

    Feature B (commodity-level) is now itself a conjunction, per
    §17.3/§17.4: a high percentile alone is NOT sufficient -- it must
    ALSO be a rare value (max_tie_share below threshold, i.e. few other
    stations share it) AND a genuinely large magnitude (value_ratio
    above threshold) before being called anomalous. This is what
    correctly separates gold/Heck Silo (percentile=1.0, tie_share=0.02%,
    value_ratio=1.42 -- all three conditions met) from gallite's 143-way
    tie (percentile=1.0, tie_share=2.98%, likely a common ceiling) even
    though both score percentile=1.0.

    `commodity_absolute_floor` (Feature B v3, §19.5/§20): OPTIONAL --
    when given, ALSO requires value_difference_absolute >= this many
    credits. Found necessary because value_ratio alone is purely
    multiplicative and flags economically meaningless swings on cheap
    commodities (hydrogenfuel: global median 80cr, a mere ~80-100cr
    absolute difference already produces a 2x ratio). Left optional
    (None = no floor applied) rather than a fixed number, since §20
    found the "right" floor shape (flat credits vs. commodity-relative
    vs. something else) is itself still an open, uncalibrated design
    choice -- callers experimenting with candidate floors pass one in,
    production code does not get a silently-baked-in default."""
    station_anomalous = (
        assessment.station_median_ratio is not None and assessment.station_median_ratio >= station_ratio_threshold
    )

    commodity_anomalous = False
    stats = assessment.worst_commodity_stats
    if stats is not None:
        commodity_anomalous = _is_commodity_anomalous(
            stats, commodity_percentile_threshold, commodity_max_tie_share_threshold,
            commodity_value_ratio_threshold, commodity_absolute_floor,
        )

    if station_anomalous and commodity_anomalous:
        return "STRONG_ANOMALY"
    if station_anomalous:
        return "STATION_ANOMALY"
    if commodity_anomalous:
        return "COMMODITY_ANOMALY"
    return "NORMAL"


@dataclass(frozen=True)
class PersistenceInfo:
    """Diagnostic metadata only (§19/§22) -- NOT an anomaly-score input.
    `persistence_ratio` of 1.0 means "flagged every day it was
    observed"; per §19.4 this does NOT mean "more likely corrupted."""

    station_id: int
    anomaly_days: int
    observed_days: int
    persistence_ratio: float  # anomaly_days / observed_days


def compute_persistence(
    daily_anomaly_station_ids: list[set[int]],
    daily_observed_station_ids: list[set[int]],
) -> dict[int, PersistenceInfo]:
    """`daily_anomaly_station_ids[i]` = the set of station_ids classified
    COMMODITY_ANOMALY or STRONG_ANOMALY on day i (caller's own classify()
    calls, one set per day). `daily_observed_station_ids[i]` = every
    station_id that had a valid assessment that day at all (anomalous or
    not) -- needed so a station's persistence_ratio is relative to how
    often it was actually observed, not to the total number of days
    sampled (a station only seen on 2 of 7 days should be judged against
    those 2, not diluted by the 5 days it wasn't even present).

    Returns one PersistenceInfo per station_id that was anomalous on at
    least one day -- stations never flagged are simply absent, not
    included with anomaly_days=0, since this is metadata for anomaly
    candidates, not a full station census."""
    if len(daily_anomaly_station_ids) != len(daily_observed_station_ids):
        raise ValueError("daily_anomaly_station_ids and daily_observed_station_ids must have the same length")

    anomaly_day_counts: dict[int, int] = defaultdict(int)
    for day_anomalies in daily_anomaly_station_ids:
        for station_id in day_anomalies:
            anomaly_day_counts[station_id] += 1

    observed_day_counts: dict[int, int] = defaultdict(int)
    for day_observed in daily_observed_station_ids:
        for station_id in day_observed:
            observed_day_counts[station_id] += 1

    result = {}
    for station_id, anomaly_days in anomaly_day_counts.items():
        observed_days = observed_day_counts.get(station_id, 0)
        if observed_days == 0:
            # a station flagged anomalous on a day it's absent from the
            # matching "observed" set is a caller bug, not silently
            # divided-by-zero here.
            raise ValueError(f"station {station_id} has anomaly_days>0 but observed_days=0 -- inconsistent input")
        result[station_id] = PersistenceInfo(
            station_id=station_id,
            anomaly_days=anomaly_days,
            observed_days=observed_days,
            persistence_ratio=anomaly_days / observed_days,
        )
    return result


@dataclass(frozen=True)
class CommodityAnomalyDetail:
    commodity_name: str
    stats: CommodityPriceStats


@dataclass(frozen=True)
class StationAnomalyProfile:
    """Feature B v4 (design doc §23, "T4-E group structure") --
    diagnostic only, not yet wired into classify(). §22's transient-
    candidate investigation found that "commodity-level anomaly"
    (Feature B, judged on a single "worst" commodity) cannot tell apart
    two structurally different real patterns:

      Heck Silo (gold):        1 unrelated commodity spikes, everything
                                else at the station is unremarkable
      mining-hotspot stations: MANY related high-value minerals
                                (platinum, osmium, painite, palladium,
                                gold, silver, ...) are ALL elevated
                                together, consistently across days --
                                a real, explainable local market
                                condition, not corruption

    `anomalous_commodity_count` counts every one of a station's own
    reference commodities that independently satisfies
    _is_commodity_anomalous (not just the single "worst" one that
    PriceAnomalyAssessment/classify() look at) -- Heck Silo should
    score close to 1, hotspot stations should score much higher.
    `anomaly_value_concentration` = the single largest
    value_difference_absolute among the anomalous set, divided by
    their sum -- close to 1.0 means one commodity accounts for nearly
    all of the "anomaly budget" (Heck Silo shape); much lower than 1.0
    means the anomaly is spread across several commodities (hotspot
    shape). None when no commodity is anomalous."""

    station_id: int
    anomalous_commodities: tuple[CommodityAnomalyDetail, ...]
    anomalous_commodity_count: int
    anomaly_value_concentration: float | None


def compute_station_anomaly_profile(
    station_id: int,
    deduped: dict[tuple[int, str], SellObservation],
    commodity_stats: dict[tuple[int, str], CommodityPriceStats],
    commodity_percentile_threshold: float,
    commodity_max_tie_share_threshold: float,
    commodity_value_ratio_threshold: float,
    commodity_absolute_floor: float | None = None,
) -> StationAnomalyProfile:
    """Evaluates EVERY reference commodity the station sells (not just
    the single "worst" one assess_station() picks) against the same
    per-commodity conjunction classify() uses, so the group structure
    of the anomaly (one commodity vs. several) can be examined."""
    station_commodities = [c for (sid, c) in deduped if sid == station_id]
    anomalous: list[CommodityAnomalyDetail] = []
    for c in station_commodities:
        stats = commodity_stats.get((station_id, c))
        if stats is None:
            continue
        if _is_commodity_anomalous(
            stats, commodity_percentile_threshold, commodity_max_tie_share_threshold,
            commodity_value_ratio_threshold, commodity_absolute_floor,
        ):
            anomalous.append(CommodityAnomalyDetail(commodity_name=c, stats=stats))

    concentration = None
    if anomalous:
        total = sum(d.stats.value_difference_absolute for d in anomalous)
        if total > 0:
            concentration = max(d.stats.value_difference_absolute for d in anomalous) / total

    return StationAnomalyProfile(
        station_id=station_id,
        anomalous_commodities=tuple(anomalous),
        anomalous_commodity_count=len(anomalous),
        anomaly_value_concentration=concentration,
    )


@dataclass(frozen=True)
class CrossStationPatternInfo:
    """Feature B v5 (design doc §24, "Cross-Station Commodity Pattern")
    -- diagnostic only, not wired into classify(). §23's real-data
    check found 31 stations independently sharing the EXACT SAME
    anomalous-commodity combination ({cobalt, osmium, painite,
    platinum}) at near-identical value_ratio -- independent per-station
    data corruption would not be expected to reproduce a 4-commodity
    combination this precisely across unrelated stations/systems. A
    large `pattern_station_count` with tightly-clustered ratios
    (`pattern_price_similarity` close to 0) is evidence the pattern
    reflects a real, shared galaxy-wide/regional economic condition --
    evidence AGAINST corruption, not for it. A pattern seen at only one
    station (pattern_station_count=1, similarity=None) cannot be
    corroborated this way, which is a different, weaker kind of
    evidence -- it does NOT by itself prove corruption either, only
    that no cross-station confirmation exists yet."""

    station_id: int
    commodity_pattern: frozenset[str]
    pattern_station_count: int  # distinct stations (including this one) sharing the exact same commodity_pattern
    pattern_price_similarity: float | None  # mean coefficient of variation of value_ratio per commodity across those stations; None if pattern_station_count==1 (nothing to compare against)


def compute_cross_station_patterns(
    profiles: dict[int, StationAnomalyProfile],
) -> dict[int, CrossStationPatternInfo]:
    """Groups stations (from an already-computed set of
    StationAnomalyProfile, e.g. one per station in a day's population)
    by the exact SET of commodities each finds anomalous, then measures
    how many independent stations share that combination and how
    tightly their per-commodity value_ratio clusters within it. Only
    stations with at least one anomalous commodity are included in the
    result (a station with zero has no pattern to compare)."""
    by_pattern: dict[frozenset[str], list[int]] = defaultdict(list)
    for station_id, profile in profiles.items():
        if profile.anomalous_commodity_count == 0:
            continue
        pattern = frozenset(d.commodity_name for d in profile.anomalous_commodities)
        by_pattern[pattern].append(station_id)

    result: dict[int, CrossStationPatternInfo] = {}
    for pattern, station_ids in by_pattern.items():
        similarity = None
        if len(station_ids) >= 2:
            coefficients_of_variation = []
            for commodity in pattern:
                ratios = [
                    detail.stats.value_ratio
                    for sid in station_ids
                    for detail in profiles[sid].anomalous_commodities
                    if detail.commodity_name == commodity
                ]
                if len(ratios) >= 2:
                    mean_ratio = statistics.mean(ratios)
                    if mean_ratio > 0:
                        coefficients_of_variation.append(statistics.stdev(ratios) / mean_ratio)
            if coefficients_of_variation:
                similarity = statistics.mean(coefficients_of_variation)

        for station_id in station_ids:
            result[station_id] = CrossStationPatternInfo(
                station_id=station_id,
                commodity_pattern=pattern,
                pattern_station_count=len(station_ids),
                pattern_price_similarity=similarity,
            )
    return result


def refine_with_cross_station_pattern(
    label: str,
    pattern_info: CrossStationPatternInfo | None,
    shared_pattern_min_stations: int,
) -> str:
    """Provisional Threshold Calibration (design doc §25) -- combines
    classify()'s Feature A/B verdict with Feature B v5's cross-station
    corroboration to separate "explained by a real, reproduced market
    condition" from "still unconfirmed either way." Only refines
    COMMODITY_ANOMALY/STRONG_ANOMALY labels; NORMAL/STATION_ANOMALY pass
    through unchanged (this function has no opinion on station-level
    anomalies, only on the commodity-level signal §24 investigated).

    Returns "KNOWN_MARKET_PATTERN" when `pattern_info` shows the
    station's exact anomalous-commodity combination is shared by at
    least `shared_pattern_min_stations` independent stations (§24.2's
    cobalt/osmium/painite/platinum group: 6 stations, ratio similarity
    0.00004) -- evidence FOR a real shared condition, not corruption.

    Returns "SUSPICIOUS" when no such corroboration exists (pattern_info
    is None, or its pattern is seen at fewer than the threshold) --
    this does NOT mean "confirmed corruption," only "not yet explained
    by cross-station repetition." §24.3's W8Y-WVM and Heck Silo both
    remain SUSPICIOUS under this definition -- they are the project's
    Known Suspicious References (not Known Positives): plausible
    candidates for genuine anomalies, never claimed as confirmed."""
    if label not in ("COMMODITY_ANOMALY", "STRONG_ANOMALY"):
        return label
    if pattern_info is not None and pattern_info.pattern_station_count >= shared_pattern_min_stations:
        return "KNOWN_MARKET_PATTERN"
    return "SUSPICIOUS"
