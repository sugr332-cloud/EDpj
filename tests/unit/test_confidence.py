from __future__ import annotations

import datetime as dt

import pytest

from app.routing.time import TimeEstimate
from app.scoring.confidence import (
    FRESHNESS_FLOOR,
    FRESHNESS_FLOOR_THRESHOLD,
    FRESHNESS_FULL_THRESHOLD,
    calculate_confidence,
    market_freshness,
)

NOW = dt.datetime(2026, 8, 20, 12, 0, 0, tzinfo=dt.timezone.utc)


def _component(confidence: float) -> TimeEstimate:
    return TimeEstimate(segment_type="mining_cycle", status="estimated", seconds=120.0, confidence=confidence, basis="")


class TestMarketFreshnessBoundaries:
    def test_no_market_observations_is_fully_fresh(self):
        assert market_freshness([], now=NOW) == 1.0

    def test_just_under_full_threshold_is_1_00(self):
        observed_at = NOW - (FRESHNESS_FULL_THRESHOLD - dt.timedelta(minutes=1))  # 14 min old
        assert market_freshness([observed_at], now=NOW) == 1.0

    def test_exactly_at_full_threshold_is_1_00(self):
        observed_at = NOW - FRESHNESS_FULL_THRESHOLD  # exactly 15 min old
        assert market_freshness([observed_at], now=NOW) == 1.0

    def test_just_over_full_threshold_starts_decaying(self):
        observed_at = NOW - (FRESHNESS_FULL_THRESHOLD + dt.timedelta(minutes=1))  # 16 min old
        assert market_freshness([observed_at], now=NOW) < 1.0

    def test_just_under_floor_threshold_is_above_floor(self):
        observed_at = NOW - (FRESHNESS_FLOOR_THRESHOLD - dt.timedelta(seconds=1))  # just under 24h
        assert market_freshness([observed_at], now=NOW) > FRESHNESS_FLOOR

    def test_exactly_at_floor_threshold_is_the_floor(self):
        observed_at = NOW - FRESHNESS_FLOOR_THRESHOLD  # exactly 24h old
        assert market_freshness([observed_at], now=NOW) == FRESHNESS_FLOOR

    def test_just_over_floor_threshold_stays_at_floor(self):
        observed_at = NOW - (FRESHNESS_FLOOR_THRESHOLD + dt.timedelta(seconds=1))  # 24h + 1s old
        assert market_freshness([observed_at], now=NOW) == FRESHNESS_FLOOR

    def test_midpoint_of_decay_range_interpolates_linearly(self):
        midpoint_age = FRESHNESS_FULL_THRESHOLD + (FRESHNESS_FLOOR_THRESHOLD - FRESHNESS_FULL_THRESHOLD) / 2
        expected = 1.0 - 0.5 * (1.0 - FRESHNESS_FLOOR)
        assert market_freshness([NOW - midpoint_age], now=NOW) == pytest.approx(expected)


class TestMarketFreshnessAggregation:
    def test_multiple_observations_use_the_minimum_not_the_product(self):
        fresh = NOW - dt.timedelta(minutes=5)  # 1.00
        stale = NOW - FRESHNESS_FLOOR_THRESHOLD  # 0.50 (floor)
        # PRODUCT would give 1.00 * 0.50 = 0.50 too here by coincidence,
        # so use a mid-decay value to distinguish MIN from PRODUCT.
        mid = NOW - (FRESHNESS_FULL_THRESHOLD + (FRESHNESS_FLOOR_THRESHOLD - FRESHNESS_FULL_THRESHOLD) / 2)  # ~0.75
        result = market_freshness([fresh, mid, stale], now=NOW)
        assert result == FRESHNESS_FLOOR  # the single worst observation wins, not a compounded product


class TestCalculateConfidence:
    def test_generation_confidence_is_retained_in_the_product(self):
        # No market observations, single fully-confident horizon component:
        # the only thing left that can move the result is generation_confidence.
        high = calculate_confidence(1.0, {"mining_cycle": _component(0.85)}, [], now=NOW)
        low = calculate_confidence(0.75, {"mining_cycle": _component(0.85)}, [], now=NOW)
        assert high == pytest.approx(0.85)
        assert low == pytest.approx(0.75 * 0.85)
        assert low < high

    def test_all_horizon_components_are_multiplied_together(self):
        components = {
            "jump": _component(0.85),
            "dock": _component(0.85),
        }
        result = calculate_confidence(1.0, components, [], now=NOW)
        assert result == pytest.approx(0.85 * 0.85)

    def test_market_freshness_is_applied_as_a_final_factor(self):
        stale_observation = NOW - FRESHNESS_FLOOR_THRESHOLD
        result = calculate_confidence(1.0, {"mining_cycle": _component(0.85)}, [stale_observation], now=NOW)
        assert result == pytest.approx(0.85 * FRESHNESS_FLOOR)

    def test_no_market_observations_leaves_confidence_unaffected_by_freshness(self):
        result = calculate_confidence(1.0, {"mining_cycle": _component(0.85)}, [], now=NOW)
        assert result == pytest.approx(0.85)
