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


def classify(
    assessment: PriceAnomalyAssessment,
    station_ratio_threshold: float,
    commodity_percentile_threshold: float,
    commodity_max_tie_share_threshold: float,
    commodity_value_ratio_threshold: float,
) -> str:
    """Two-axis classification (design doc §16-17, "T4-E"). Thresholds
    are caller-supplied, never hardcoded here -- production values
    remain UNRESOLVED per §14/§16.5/§17.4 pending more calibration
    examples.

    Feature B (commodity-level) is now itself a conjunction, per
    §17.3/§17.4: a high percentile alone is NOT sufficient -- it must
    ALSO be a rare value (max_tie_share below threshold, i.e. few other
    stations share it) AND a genuinely large magnitude (value_ratio
    above threshold) before being called anomalous. This is what
    correctly separates gold/Heck Silo (percentile=1.0, tie_share=0.02%,
    value_ratio=1.42 -- all three conditions met) from gallite's 143-way
    tie (percentile=1.0, tie_share=2.98%, likely a common ceiling) even
    though both score percentile=1.0."""
    station_anomalous = (
        assessment.station_median_ratio is not None and assessment.station_median_ratio >= station_ratio_threshold
    )

    commodity_anomalous = False
    stats = assessment.worst_commodity_stats
    if stats is not None:
        commodity_anomalous = (
            stats.percentile >= commodity_percentile_threshold
            and stats.max_tie_share <= commodity_max_tie_share_threshold
            and stats.value_ratio >= commodity_value_ratio_threshold
        )

    if station_anomalous and commodity_anomalous:
        return "STRONG_ANOMALY"
    if station_anomalous:
        return "STATION_ANOMALY"
    if commodity_anomalous:
        return "COMMODITY_ANOMALY"
    return "NORMAL"
