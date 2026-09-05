"""Market volatility metrics — Phase 2-5A.

Spec (docs/PHASE_2_5A_MARKET_PREDICTABILITY_IMPLEMENTATION_BASELINE_V0.1.md
§6). Pure functions only, no DB/session — same pattern as
app/calibration/metrics.py.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class Observation:
    observed_at: datetime
    price: int
    demand: int


def pair_observations(
    observations: list[Observation], max_gap: timedelta
) -> tuple[list[tuple[Observation, Observation]], list[timedelta]]:
    """`observations` must already be sorted by observed_at ascending.
    Returns (pairs within max_gap -- usable for price/demand volatility,
    every adjacent pair's gap -- used for gap statistics regardless of
    whether it was too large to use for volatility). A gap that exceeds
    max_gap is never treated as "no change" (docs/MARKET_PREDICTABILITY_SPEC_V0.1.md
    §4.1: missing periods are never interpolated as zero volatility)."""
    pairs_within_gap: list[tuple[Observation, Observation]] = []
    all_gaps: list[timedelta] = []
    for prev, curr in zip(observations, observations[1:]):
        gap = curr.observed_at - prev.observed_at
        all_gaps.append(gap)
        if gap <= max_gap:
            pairs_within_gap.append((prev, curr))
    return pairs_within_gap, all_gaps


def price_change_ratio(prev: Observation, curr: Observation) -> float | None:
    """None if `prev.price` is invalid (<= 0) -- excluded from the
    calculation rather than producing a division artifact (§4.2)."""
    if prev.price <= 0:
        return None
    return abs(curr.price - prev.price) / prev.price


def demand_change_ratio(prev: Observation, curr: Observation, demand_floor: int) -> float:
    denominator = max(prev.demand, demand_floor)
    return abs(curr.demand - prev.demand) / denominator


def median_and_p95(values: list[float]) -> tuple[float | None, float | None]:
    """(None, None) for an empty input. p95 uses statistics.quantiles'
    exclusive method (n=100), a deterministic, dependency-free
    implementation -- not a bespoke interpolation."""
    if not values:
        return None, None
    if len(values) == 1:
        return values[0], values[0]
    median = statistics.median(values)
    p95 = statistics.quantiles(values, n=100, method="exclusive")[94]
    return median, p95
