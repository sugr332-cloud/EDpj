from __future__ import annotations

from app.routing.time import TimeEstimate
from app.scoring.reason_facts import (
    confidence_reason_facts,
    horizon_reason_facts,
    score_reason_fact,
    value_reason_fact,
)


def _component(segment_type: str, seconds: float, confidence: float) -> TimeEstimate:
    return TimeEstimate(segment_type=segment_type, status="estimated", seconds=seconds, confidence=confidence, basis="")


class TestHorizonReasonFacts:
    def test_one_fact_per_segment_always_negative(self):
        components = {"mining_cycle": _component("mining_cycle", 120.0, 0.85)}
        facts = horizon_reason_facts(components)
        assert len(facts) == 1
        assert facts[0].factor == "mining_cycle"
        assert facts[0].effect == "negative"
        assert facts[0].value == 120.0

    def test_multiple_segments_produce_multiple_facts(self):
        components = {
            "jump": _component("jump", 30.0, 0.85),
            "dock": _component("dock", 15.0, 0.85),
        }
        facts = horizon_reason_facts(components)
        assert {f.factor for f in facts} == {"jump", "dock"}
        assert all(f.effect == "negative" for f in facts)


class TestValueAndScoreReasonFacts:
    def test_value_reason_fact_is_always_positive(self):
        fact = value_reason_fact(44586.0)
        assert fact.factor == "expected_value"
        assert fact.effect == "positive"
        assert fact.value == 44586.0

    def test_score_reason_fact_is_always_positive(self):
        fact = score_reason_fact(1337580.0)
        assert fact.factor == "score_per_hour"
        assert fact.effect == "positive"
        assert fact.value == 1337580.0


class TestConfidenceReasonFacts:
    def test_two_facts_confidence_and_freshness_both_negative_regardless_of_value(self):
        # Even a perfect 1.00/1.00 case stays "negative" -- effect is fixed
        # per factor (§2), not conditional on whether decay actually happened.
        facts = confidence_reason_facts(1.0, {"mining_cycle": _component("mining_cycle", 120.0, 1.0)}, freshness=1.0)
        assert len(facts) == 2
        by_factor = {f.factor: f for f in facts}
        assert by_factor["confidence"].effect == "negative"
        assert by_factor["confidence"].value == 1.0
        assert by_factor["data_freshness"].effect == "negative"
        assert by_factor["data_freshness"].value == 1.0

    def test_confidence_value_reflects_generation_confidence_and_horizon_product(self):
        facts = confidence_reason_facts(0.75, {"mining_cycle": _component("mining_cycle", 120.0, 0.85)}, freshness=0.9)
        by_factor = {f.factor: f for f in facts}
        assert by_factor["confidence"].value == 0.75 * 0.85
        assert by_factor["data_freshness"].value == 0.9
