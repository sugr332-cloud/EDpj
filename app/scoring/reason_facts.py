"""ReasonFact generation — Phase 2-5D.

Spec (docs/PHASE_2_5D_EXPLAINABILITY_DESIGN_BASELINE_V0.1.md §1/§2).

Called from app/scoring/pipeline.py's loop immediately after each stage's
calculation -- never reconstructed after Ranking (docs/PHASE_2_0_DESIGN_BASELINE_V0.1.md
§2.3). These functions are pure: they only interpret already-computed
values, never recompute anything Horizon/Value/Confidence/Score already
decided.

`effect` is fixed per factor (§2), not conditional on the value itself:

    expected_value / score_per_hour -> always "positive" (higher is better,
        by definition -- there's no "bad" expected_value to distinguish)
    segment_type (Horizon)          -> always "negative" (time is a cost)
    confidence / data_freshness     -> always "negative" (framed as decay
        factors on the raw value/score, even when their value happens to
        be 1.00 -- not "good news, no decay happened")
"""
from __future__ import annotations

from app.routing.time import HorizonComponent
from app.scoring.confidence import component_confidence_product
from app.scoring.models import ReasonFact


def horizon_reason_facts(components: dict[str, HorizonComponent]) -> list[ReasonFact]:
    return [
        ReasonFact(factor=segment_type, effect="negative", value=component.seconds, comparison=None)
        for segment_type, component in components.items()
    ]


def value_reason_fact(expected_value: float) -> ReasonFact:
    return ReasonFact(factor="expected_value", effect="positive", value=expected_value, comparison=None)


def confidence_reason_facts(
    generation_confidence: float, horizon_components: dict[str, HorizonComponent], freshness: float
) -> list[ReasonFact]:
    product = component_confidence_product(generation_confidence, horizon_components)
    return [
        ReasonFact(factor="confidence", effect="negative", value=product, comparison=None),
        ReasonFact(factor="data_freshness", effect="negative", value=freshness, comparison=None),
    ]


def score_reason_fact(score_per_hour: float) -> ReasonFact:
    return ReasonFact(factor="score_per_hour", effect="positive", value=score_per_hour, comparison=None)
