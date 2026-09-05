"""Phase 2-2/2-3 candidate pipeline: generate -> filter -> horizon -> value -> classify.

Spec (docs/PHASE_2_2_CANDIDATE_GENERATION_DESIGN_BASELINE_V0.1.md §1, §9, §10, §11;
docs/PHASE_2_3_HORIZON_VALUE_DESIGN_BASELINE_V0.1.md §0/§1/§6/§7).

Value is attempted for every passed candidate regardless of horizon
completeness -- `complete`/`incomplete` classification requires BOTH axes
(`is_scoreable`: `blocking_segments == [] AND expected_value is not None
AND value_unavailable_reason is None`), not horizon alone. A candidate
that is horizon-complete but value-unavailable (e.g. `bio_current_body`,
whose species value model doesn't exist yet) still ends up in
`incomplete`, holding whatever it does have -- see IncompleteCandidate's
docstring. `confidence` on a `complete` `ActionCandidate` still only
holds the generation-stage `generation_confidence` (not the real composed
confidence formula, Ranking's job in Phase 2-4) — they are *scoreable
drafts*, not finished recommendations.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.bio.candidates import DEFAULT_DISTANCE_LIMIT_LY, generate_bio_candidates
from app.db.models.player import PlayerState
from app.mining.candidates import generate_mining_candidates
from app.scoring.filters import apply_filters
from app.scoring.models import (
    ActionCandidate,
    DraftCandidate,
    HorizonComponent,
    IncompleteCandidate,
    RejectedCandidate,
    build_horizon,
    is_scoreable,
)
from app.scoring.value import calculate_score, calculate_value


@dataclass
class CandidatePipelineResult:
    complete: list[ActionCandidate]
    incomplete: list[IncompleteCandidate]
    rejected: list[RejectedCandidate]


def _blocking_segments(components: dict[str, HorizonComponent]) -> list[str]:
    return [segment_type for segment_type, component in components.items() if component.status == "unavailable"]


def generate_and_classify(
    session: Session,
    player_state: PlayerState,
    mining_enabled: bool = True,
    bio_enabled: bool = True,
    distance_limit_ly: float = DEFAULT_DISTANCE_LIMIT_LY,
) -> CandidatePipelineResult:
    drafts: list[DraftCandidate] = []
    if mining_enabled:
        drafts += generate_mining_candidates(session)
    if bio_enabled:
        drafts += generate_bio_candidates(session, player_state, distance_limit_ly)

    passed, rejected = apply_filters(drafts)

    complete: list[ActionCandidate] = []
    incomplete: list[IncompleteCandidate] = []
    for draft in passed:
        components, _horizon_complete, total_seconds = build_horizon(draft.required_segments, session)
        blocking = _blocking_segments(components)
        expected_value, value_unavailable_reason = calculate_value(draft, session)

        if is_scoreable(blocking, expected_value, value_unavailable_reason, total_seconds):
            complete.append(
                ActionCandidate(
                    action=draft.action,
                    target=draft.target,
                    expected_value=expected_value,
                    action_horizon_seconds=total_seconds,
                    horizon_components=components,
                    horizon_complete=True,
                    score_per_hour=calculate_score(expected_value, total_seconds),
                    confidence=draft.generation_confidence if draft.generation_confidence is not None else 0.0,
                    reason="",
                )
            )
        else:
            reasons = []
            if blocking:
                reasons.append(f"{'/'.join(blocking)} time estimate unavailable")
            elif total_seconds is None or total_seconds <= 0:
                reasons.append(f"action horizon is not a positive duration ({total_seconds}s)")
            if value_unavailable_reason:
                reasons.append(f"value unavailable: {value_unavailable_reason}")
            incomplete.append(
                IncompleteCandidate(
                    action=draft.action,
                    target=draft.target,
                    breakdown=components,
                    blocking_segments=blocking,
                    reason=" -- ".join(reasons) + " -- cannot compute a score yet",
                    expected_value=expected_value,
                    value_unavailable_reason=value_unavailable_reason,
                )
            )

    return CandidatePipelineResult(complete=complete, incomplete=incomplete, rejected=rejected)
