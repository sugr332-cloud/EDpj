"""Ranking / Recommendation assembly — Phase 2-4.

Spec (docs/PHASE_2_4_RANKING_DESIGN_BASELINE_V0.1.md v0.2).

Operates only on `CandidatePipelineResult.complete` (Phase 2-3's
`is_scoreable` output) — `incomplete` passes straight through unchanged
into `NextActionResponse.incomplete`; this module never inspects it.

`confidence` is read as an already-existing input (still Phase 2-2's
`generation_confidence` passthrough today) and used only as a
`>= MIN_ACTION_CONFIDENCE` gate before ranking -- it is never blended
into the sort key. The real `Π(component_confidence) × freshness_factor`
composition, and ReasonFact/DataSource population, are Phase 2-5.
"""
from __future__ import annotations

from app.scoring.models import (
    ActionCandidate,
    BioTarget,
    MiningTarget,
    NextActionResponse,
    Recommendation,
    RejectedCandidate,
)
from app.scoring.pipeline import CandidatePipelineResult

MIN_ACTION_CONFIDENCE = 0.50
ALTERNATIVES_LIMIT = 3

NO_CANDIDATES_REASON = "有効な候補行動がありません"
ALL_BELOW_CONFIDENCE_REASON = "候補はあるが confidence が閾値未満です"


def target_id(action: str, target: BioTarget | MiningTarget) -> str:
    """A deterministic, display/comparison-only identifier -- not a DB
    key. Relies on the existing candidate-generation invariant that the
    same (action, target) pair is never generated twice within one
    pipeline run, so this doubles as a stable tie-break key (§3/§4)."""
    if isinstance(target, MiningTarget):
        if target.station_id is not None:
            return f"{action}:station:{target.station_id}"
        return f"{action}:ring:{target.system_name}"
    return f"{action}:body:{target.system_name}:{target.body_name}"


def _sort_key(candidate: ActionCandidate) -> tuple[float, float, float, str]:
    return (
        -candidate.score_per_hour,
        -candidate.expected_value,
        candidate.action_horizon_seconds,
        target_id(candidate.action, candidate.target),
    )


def rank_candidates(
    candidates: list[ActionCandidate], min_confidence: float = MIN_ACTION_CONFIDENCE
) -> tuple[list[ActionCandidate], list[ActionCandidate]]:
    """Returns (eligible_sorted, below_threshold_sorted), both ordered by
    the same deterministic sort key (§3) -- `confidence` decides only
    which bucket a candidate falls into, never the order within one."""
    eligible = [c for c in candidates if c.confidence >= min_confidence]
    below_threshold = [c for c in candidates if c.confidence < min_confidence]
    return sorted(eligible, key=_sort_key), sorted(below_threshold, key=_sort_key)


def _to_recommendation(candidate: ActionCandidate) -> Recommendation:
    return Recommendation(
        action=candidate.action,
        target=candidate.target,
        expected_value=candidate.expected_value,
        action_horizon_seconds=candidate.action_horizon_seconds,
        score_per_hour=candidate.score_per_hour,
        confidence=candidate.confidence,
        breakdown=candidate.horizon_components,
        reasons=candidate.reasons,
        data_sources=candidate.data_sources,
    )


def select_recommendation(eligible_sorted: list[ActionCandidate]) -> Recommendation | None:
    """§7: no floor beyond the confidence gate already applied in
    `rank_candidates` -- the top-ranked eligible candidate is always the
    recommendation, however small its score_per_hour."""
    if not eligible_sorted:
        return None
    return _to_recommendation(eligible_sorted[0])


def build_alternatives(
    eligible_sorted: list[ActionCandidate], limit: int = ALTERNATIVES_LIMIT
) -> list[Recommendation]:
    return [_to_recommendation(c) for c in eligible_sorted[1 : 1 + limit]]


def build_score_rejections(
    eligible_sorted: list[ActionCandidate], below_threshold_sorted: list[ActionCandidate]
) -> list[RejectedCandidate]:
    """Every non-winning scoreable candidate, without a limit -- unlike
    `build_alternatives`, this is the unabridged audit trail (§6)."""
    rejections: list[RejectedCandidate] = []
    if eligible_sorted:
        winner_score = eligible_sorted[0].score_per_hour
        for candidate in eligible_sorted[1:]:
            rejections.append(
                RejectedCandidate(
                    category="score",
                    action=candidate.action,
                    target_id=target_id(candidate.action, candidate.target),
                    reason_code="lower_score",
                    value=candidate.score_per_hour,
                    comparison=winner_score,
                )
            )
    for candidate in below_threshold_sorted:
        rejections.append(
            RejectedCandidate(
                category="score",
                action=candidate.action,
                target_id=target_id(candidate.action, candidate.target),
                reason_code="confidence_below_threshold",
                value=candidate.confidence,
                comparison=MIN_ACTION_CONFIDENCE,
            )
        )
    return rejections


def assemble_next_action_response(result: CandidatePipelineResult) -> NextActionResponse:
    """§8/§9: the two empty-recommendation cases carry different `reason`
    text so a caller can tell "no candidates at all" apart from "candidates
    exist but none are trustworthy enough"."""
    if not result.complete:
        return NextActionResponse(
            next_action=None,
            recommendation=None,
            alternatives=[],
            incomplete=result.incomplete,
            rejected=list(result.rejected),
            reason=NO_CANDIDATES_REASON,
        )

    eligible_sorted, below_threshold_sorted = rank_candidates(result.complete)
    rejected = [*result.rejected, *build_score_rejections(eligible_sorted, below_threshold_sorted)]

    if not eligible_sorted:
        return NextActionResponse(
            next_action=None,
            recommendation=None,
            alternatives=[],
            incomplete=result.incomplete,
            rejected=rejected,
            reason=ALL_BELOW_CONFIDENCE_REASON,
        )

    recommendation = select_recommendation(eligible_sorted)
    return NextActionResponse(
        next_action=recommendation.action,
        recommendation=recommendation,
        alternatives=build_alternatives(eligible_sorted),
        incomplete=result.incomplete,
        rejected=rejected,
        reason=None,
    )
