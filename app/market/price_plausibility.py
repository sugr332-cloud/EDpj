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
