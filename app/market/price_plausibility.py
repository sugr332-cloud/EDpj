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


def compute_commodity_percentiles(
    deduped: dict[tuple[int, str], SellObservation],
) -> dict[tuple[int, str], float]:
    """Feature B (design doc §16, "T4-E"): for EVERY (station, commodity)
    pair, the percentile rank of that station's price within THAT
    commodity's own population (not the station's basket median).
    Complementary to compute_station_median_ratio -- §16.3's real
    finding was that a station can be entirely unremarkable at the
    station level (median ratio near 1.0) while one specific commodity
    it sells is the single most extreme value in that commodity's whole
    population (P100). Station-level aggregation cannot see this; only
    a per-commodity check can."""
    prices_by_commodity: dict[str, list[int]] = defaultdict(list)
    for (_, commodity_name), obs in deduped.items():
        prices_by_commodity[commodity_name].append(obs.sell_price)
    sorted_prices = {name: sorted(prices) for name, prices in prices_by_commodity.items()}

    percentiles: dict[tuple[int, str], float] = {}
    for key, obs in deduped.items():
        population = sorted_prices[obs.commodity_name]
        n = len(population)
        if n == 0:
            continue
        below_or_equal = sum(1 for p in population if p <= obs.sell_price)
        percentiles[key] = below_or_equal / n
    return percentiles


@dataclass(frozen=True)
class PriceAnomalyAssessment:
    station_id: int
    station_median_ratio: float | None  # Feature A -- None if below min_reference_commodities
    worst_commodity_percentile: float | None  # Feature B -- max percentile among this station's own commodities
    worst_commodity_name: str | None
    n_reference_commodities: int


def assess_station(
    station_id: int,
    deduped: dict[tuple[int, str], SellObservation],
    station_median_ratio: dict[int, float],
    commodity_percentiles: dict[tuple[int, str], float],
) -> PriceAnomalyAssessment:
    """Assembles both features for one station. Does NOT classify --
    per the explicit design decision (§16.5) not to fix thresholds
    before more examples are gathered. Callers apply their own
    threshold pair via `classify()` below, kept as parameters rather
    than module constants."""
    station_commodities = [c for (sid, c) in deduped if sid == station_id]
    worst_name, worst_pct = None, None
    for c in station_commodities:
        pct = commodity_percentiles.get((station_id, c))
        if pct is not None and (worst_pct is None or pct > worst_pct):
            worst_pct, worst_name = pct, c

    return PriceAnomalyAssessment(
        station_id=station_id,
        station_median_ratio=station_median_ratio.get(station_id),
        worst_commodity_percentile=worst_pct,
        worst_commodity_name=worst_name,
        n_reference_commodities=len(station_commodities),
    )


def classify(
    assessment: PriceAnomalyAssessment,
    station_ratio_threshold: float,
    commodity_percentile_threshold: float,
) -> str:
    """Two-axis classification (design doc §16, "T4-E"). Thresholds are
    caller-supplied, never hardcoded here -- production values remain
    UNRESOLVED per §14/§16.5 pending more calibration examples."""
    station_anomalous = (
        assessment.station_median_ratio is not None and assessment.station_median_ratio >= station_ratio_threshold
    )
    commodity_anomalous = (
        assessment.worst_commodity_percentile is not None
        and assessment.worst_commodity_percentile >= commodity_percentile_threshold
    )
    if station_anomalous and commodity_anomalous:
        return "STRONG_ANOMALY"
    if station_anomalous:
        return "STATION_ANOMALY"
    if commodity_anomalous:
        return "COMMODITY_ANOMALY"
    return "NORMAL"
