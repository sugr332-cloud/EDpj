"""Effective price model — Phase 2-3.

Spec (IMPLEMENTATION_SPEC_V0.2.md §10.1, docs/PHASE_2_3_HORIZON_VALUE_DESIGN_BASELINE_V0.1.md §4.1):
demand relative to cargo held/expected penalizes the listed sell price
piecewise-linearly. Callers only invoke this where `demand > 0` (both
candidate generation and Value already filter to `demand > 0` rows) —
`r = cargo / demand` is undefined at demand=0.
"""
from __future__ import annotations

_LOW_RATIO = 0.25
_HIGH_RATIO = 0.80
_NO_PENALTY = 1.00
_MAX_PENALTY = 0.45


def demand_penalty(cargo: float, demand: int) -> float:
    r = cargo / demand
    if r <= _LOW_RATIO:
        return _NO_PENALTY
    if r >= _HIGH_RATIO:
        return _MAX_PENALTY
    fraction = (r - _LOW_RATIO) / (_HIGH_RATIO - _LOW_RATIO)
    return _NO_PENALTY + fraction * (_MAX_PENALTY - _NO_PENALTY)


def effective_price(listed_price: int, cargo: float, demand: int) -> float:
    return listed_price * demand_penalty(cargo, demand)
