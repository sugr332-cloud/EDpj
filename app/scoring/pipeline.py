"""Phase 2-2 candidate pipeline: generate -> filter -> horizon -> classify.

Spec (docs/PHASE_2_2_CANDIDATE_GENERATION_DESIGN_BASELINE_V0.1.md §1, §9, §10, §11).

Stops at Horizon Builder — Value/Confidence/Score (later Phase 2 steps,
docs/PHASE_2_0_DESIGN_BASELINE_V0.1.md §1) are not computed. `complete`
candidates come back as `ActionCandidate` with `expected_value`/
`score_per_hour` still `None` and `confidence` holding only the
generation-stage `generation_confidence` (not the real composed
confidence formula) — they are *horizon-complete drafts*, not finished
recommendations.
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
)


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
        components, horizon_complete, total_seconds = build_horizon(draft.required_segments, session)
        if horizon_complete:
            complete.append(
                ActionCandidate(
                    action=draft.action,
                    target=draft.target,
                    expected_value=None,
                    action_horizon_seconds=total_seconds,
                    horizon_components=components,
                    horizon_complete=True,
                    score_per_hour=None,
                    confidence=draft.generation_confidence if draft.generation_confidence is not None else 0.0,
                    reason="",
                )
            )
        else:
            blocking = _blocking_segments(components)
            incomplete.append(
                IncompleteCandidate(
                    action=draft.action,
                    target=draft.target,
                    breakdown=components,
                    blocking_segments=blocking,
                    reason=f"{'/'.join(blocking)} time estimate unavailable -- cannot compute a score yet",
                )
            )

    return CandidatePipelineResult(complete=complete, incomplete=incomplete, rejected=rejected)
