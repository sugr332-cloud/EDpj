"""Phase 2-2/2-3/2-5C/2-5D candidate pipeline: generate -> filter -> horizon -> value -> confidence -> classify.

Spec (docs/PHASE_2_2_CANDIDATE_GENERATION_DESIGN_BASELINE_V0.1.md §1, §9, §10, §11;
docs/PHASE_2_3_HORIZON_VALUE_DESIGN_BASELINE_V0.1.md §0/§1/§6/§7;
docs/PHASE_2_5_CONFIDENCE_EXPLAINABILITY_DESIGN_BASELINE_V0.1.md §7.2, v0.3;
docs/PHASE_2_5D_EXPLAINABILITY_DESIGN_BASELINE_V0.1.md §1).

Value is attempted for every passed candidate regardless of horizon
completeness -- `complete`/`incomplete` classification requires BOTH axes
(`is_scoreable`: `blocking_segments == [] AND expected_value is not None
AND value_unavailable_reason is None`), not horizon alone. A candidate
that is horizon-complete but value-unavailable (e.g. `bio_current_body`,
whose species value model doesn't exist yet) still ends up in
`incomplete`, holding whatever it does have -- see IncompleteCandidate's
docstring. `confidence` on a `complete` `ActionCandidate` is the real
`generation_confidence × Π(horizon component confidence) × market
freshness` composition (Phase 2-5C). `reasons`/`data_sources` are built
immediately after each stage's calculation, right here in this loop, not
reconstructed after Ranking (Phase 2-5D §1) — `narration` is still not
implemented (no CLI/API consumer exists yet, Phase 2-5D §6).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.bio.candidates import DEFAULT_DISTANCE_LIMIT_LY, generate_bio_candidates
from app.db.models.player import PlayerState
from app.mining.candidates import generate_mining_candidates
from app.scoring.confidence import calculate_confidence, market_freshness
from app.scoring.data_sources import (
    calibration_data_sources,
    cargo_state_data_source,
    loadout_data_source,
    market_data_sources,
)
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
from app.scoring.reason_facts import (
    confidence_reason_facts,
    horizon_reason_facts,
    score_reason_fact,
    value_reason_fact,
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
        value_result = calculate_value(draft, session)
        expected_value = value_result.expected_value
        value_unavailable_reason = value_result.value_unavailable_reason

        if is_scoreable(blocking, expected_value, value_unavailable_reason, total_seconds):
            generation_confidence = draft.generation_confidence if draft.generation_confidence is not None else 0.0
            now = dt.datetime.now(dt.timezone.utc)
            freshness = market_freshness(value_result.market_observed_ats, now)
            confidence = calculate_confidence(generation_confidence, components, value_result.market_observed_ats, now=now)
            score_per_hour = calculate_score(expected_value, total_seconds)

            reason_facts = (
                horizon_reason_facts(components)
                + [value_reason_fact(expected_value)]
                + confidence_reason_facts(generation_confidence, components, freshness)
                + [score_reason_fact(score_per_hour)]
            )
            data_sources = market_data_sources(value_result.market_observed_ats, now)
            if draft.action in ("mining_sell", "mining_continue"):
                cargo_ds = cargo_state_data_source(session)
                if cargo_ds is not None:
                    data_sources.append(cargo_ds)
            if draft.action == "mining_continue":
                loadout_ds = loadout_data_source(session)
                if loadout_ds is not None:
                    data_sources.append(loadout_ds)
            data_sources += calibration_data_sources(components)

            complete.append(
                ActionCandidate(
                    action=draft.action,
                    target=draft.target,
                    expected_value=expected_value,
                    action_horizon_seconds=total_seconds,
                    horizon_components=components,
                    horizon_complete=True,
                    score_per_hour=score_per_hour,
                    confidence=confidence,
                    reason="",
                    reasons=reason_facts,
                    data_sources=data_sources,
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
