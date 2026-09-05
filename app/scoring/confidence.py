"""Confidence composition — Phase 2-5C.

Spec (docs/PHASE_2_5_CONFIDENCE_EXPLAINABILITY_DESIGN_BASELINE_V0.1.md
§7/§7.2, v0.2):

    final_confidence
      = generation_confidence
      × Π(HorizonComponent confidence)
      × market_freshness

`generation_confidence` (Phase 2-2's per-candidate uncertainty, e.g.
MiningContext lacking a corroborating body context) is kept as an
explicit factor, not discarded -- it's independent of Horizon/Value
confidence and dropping it would silently lose information that used to
flow straight through to `ActionCandidate.confidence` (§7.2 decision 1).

Market/Cargo observation status confidence is always "measured" = 1.00
(§7.2) -- the multiplicative identity -- so it's never written as an
explicit ×1.00 term in code; only its *freshness* (this module's actual
job) varies.
"""
from __future__ import annotations

import datetime as dt

from app.routing.time import HorizonComponent

# Placeholder curve (§7.2) -- not calibrated against real data yet, same
# status as app/mining/price.py's demand_penalty shape it mirrors
# (flat -> linear -> flat). Revisit once Phase 2-6's historical backtest
# exists.
FRESHNESS_FULL_THRESHOLD = dt.timedelta(minutes=15)
FRESHNESS_FLOOR_THRESHOLD = dt.timedelta(hours=24)
FRESHNESS_FLOOR = 0.50


def _freshness_for_age(age: dt.timedelta) -> float:
    if age <= FRESHNESS_FULL_THRESHOLD:
        return 1.0
    if age >= FRESHNESS_FLOOR_THRESHOLD:
        return FRESHNESS_FLOOR
    total_range = (FRESHNESS_FLOOR_THRESHOLD - FRESHNESS_FULL_THRESHOLD).total_seconds()
    elapsed = (age - FRESHNESS_FULL_THRESHOLD).total_seconds()
    fraction = elapsed / total_range
    return 1.0 - fraction * (1.0 - FRESHNESS_FLOOR)


def _naive(ts: dt.datetime) -> dt.datetime:
    # SQLite's DateTime(timezone=True) doesn't round-trip tzinfo -- a row
    # read back from MarketLatest.observed_at comes back naive even
    # though it was written as UTC-aware. Strip tzinfo before comparing
    # so this never depends on which dialect stored the value (same
    # workaround used throughout this project, e.g.
    # app/mining/state.py's _find_recent_mining_refined).
    return ts.replace(tzinfo=None) if ts.tzinfo is not None else ts


def market_freshness(observed_ats: list[dt.datetime], now: dt.datetime) -> float:
    """1.00 when `observed_ats` is empty -- this candidate's value didn't
    depend on any Market observation at all, so there's nothing to decay.
    Otherwise the MIN across every observation Value actually used, not
    PRODUCT (§7.2 decision 2): a candidate touching more commodities/
    markets (mining_sell) must not be penalized merely for having more
    independently-fresh inputs -- PRODUCT would make "handles more
    commodities" look structurally less trustworthy for no real reason."""
    if not observed_ats:
        return 1.0
    now_naive = _naive(now)
    return min(_freshness_for_age(now_naive - _naive(observed_at)) for observed_at in observed_ats)


def calculate_confidence(
    generation_confidence: float,
    horizon_components: dict[str, HorizonComponent],
    market_observed_ats: list[dt.datetime],
    now: dt.datetime | None = None,
) -> float:
    now = now or dt.datetime.now(dt.timezone.utc)
    component_product = generation_confidence
    for component in horizon_components.values():
        if component.confidence is not None:
            component_product *= component.confidence
    return component_product * market_freshness(market_observed_ats, now)
