"""ActionCandidate DTO and horizon assembly.

Spec (IMPLEMENTATION_SPEC_V0.2.md §12.2): `horizon_complete` means "every
time segment *this action's* horizon is built from is available" — not
"no segment_type anywhere is unavailable". An action that doesn't need
supercruise can be `horizon_complete=True` even while a `supercruise`
TimeEstimate elsewhere is `unavailable`.

Phase 0-C scope only: `build_horizon` assembles `horizon_components` from
a caller-supplied list of required segments and derives
`horizon_complete`/`action_horizon_seconds` from them. It does not decide
how `ActionCandidate.confidence` aggregates per-segment confidences, and
does not decide how Unified Scoring treats a `horizon_complete=False`
candidate — both are deferred to Phase 2 (§12.3/§12.4). Mining/Bio
candidate generation itself (populating `action`, `target`,
`expected_value`, `score_per_hour`, `reason`) is Phase 2 and not
implemented here.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Sequence

from sqlalchemy.orm import Session

from app.routing.time import HorizonComponent, TimeEstimate, estimate_segment


@dataclass
class ActionCandidate:
    """The same object is threaded through Filter -> Horizon -> Value ->
    Confidence -> Score (design doc §1's pipeline): each later stage fills
    in more fields. `expected_value` is `float | None` for the same reason
    `action_horizon_seconds`/`score_per_hour` already are -- Phase 2-2 only
    reaches Horizon, so it's legitimately still unknown here, not a
    fabricated 0.0."""

    action: str
    target: dict | None
    expected_value: float | None
    action_horizon_seconds: float | None
    horizon_components: dict[str, TimeEstimate]
    horizon_complete: bool
    score_per_hour: float | None
    confidence: float
    reason: str
    reasons: list[ReasonFact] = field(default_factory=list)
    data_sources: list[DataSource] = field(default_factory=list)


@dataclass
class DiscoveryState:
    honked: bool = False
    fss_scanned: bool = False
    dss_scanned: bool = False


@dataclass
class BioTarget:
    """IMPLEMENTATION_SPEC_V0.2.md §21. `predicted_species`/`colony_spacing_m`
    are species-value-estimation fields (§11.1) Phase 2-2 candidate
    generation does not compute — they default empty/None here and are
    filled in by the later Value stage, not at generation time."""

    body_name: str
    system_name: str  # from Journal StarSystem / System.name -- never derived by splitting body_name (§21)
    body_suffix: str
    arrival_dist_from_star_ls: float | None  # None: the body-level position isn't always known at generation time
    gravity: float | None = None
    colony_spacing_m: int | None = None
    discovery: DiscoveryState = field(default_factory=DiscoveryState)
    time_breakdown: dict[str, float] = field(default_factory=dict)
    predicted_species: list = field(default_factory=list)  # populated by Value stage (§11.1), not Phase 2-2


@dataclass
class MiningTarget:
    """IMPLEMENTATION_SPEC_V0.2.md §21. `demand`/`cargo_demand_ratio`/
    `listed_price`/`effective_price` are Value-stage fields (§10.1) --
    None at Phase 2-2 generation time, filled in later.

    `station_id`/`commodity_name` (added Phase 2-3, docs/PHASE_2_3_HORIZON_VALUE_DESIGN_BASELINE_V0.1.md
    §4) are plumbing, not new policy: Value needs to re-query
    MarketLatest for the specific station (mining_sell/bio_return) or
    commodity (mining_continue) a candidate refers to, and the
    name-only fields above aren't a reliable re-lookup key. Both are
    already known at generation time (Station.station_id /
    MiningContext.last_refined_commodity) -- this just carries them
    through instead of re-deriving them later."""

    station_name: str
    system_name: str  # copy-paste target -- from Journal StarSystem / System.name
    parent_body_name: str | None
    station_type: str
    arrival_dist_from_star_ls: float | None
    max_landing_pad: str | None = None
    station_id: int | None = None
    commodity_name: str | None = None
    demand: int | None = None
    cargo_demand_ratio: float | None = None
    listed_price: int | None = None
    effective_price: int | None = None
    time_breakdown: dict[str, float] = field(default_factory=dict)


@dataclass
class DraftCandidate:
    """docs/PHASE_2_2_CANDIDATE_GENERATION_DESIGN_BASELINE_V0.1.md §3.
    What candidate generation produces -- deliberately no expected_value/
    score_per_hour/confidence (final): those belong to Value/Score, later
    stages this module does not implement."""

    action: str
    target: BioTarget | MiningTarget
    required_segments: list[str]
    generation_confidence: float | None = None


@dataclass
class RejectedCandidate:
    """docs/RECOMMENDATION_EXPLAINABILITY_SPEC_V0.1.md §4. Only `filter`
    (excluded before scoring — see docs/PHASE_2_2_CANDIDATE_GENERATION_DESIGN_BASELINE_V0.1.md
    §6) and `score` (passed all filters but ranked below the winner, a
    later Unified Scoring stage) categories exist; `incomplete` is
    deliberately not a RejectedCandidate category — see IncompleteCandidate
    below and docs/PHASE_2_0_DESIGN_BASELINE_V0.1.md §2.4."""

    category: str  # "filter" | "score"
    action: str
    target_id: str
    reason_code: str
    value: float | None = None
    comparison: float | None = None


@dataclass
class IncompleteCandidate:
    """docs/PHASE_2_0_DESIGN_BASELINE_V0.1.md §2.2, generalized in
    docs/PHASE_2_3_HORIZON_VALUE_DESIGN_BASELINE_V0.1.md §0/§1: a
    candidate that passed every deterministic filter but is not yet
    scoreable, for either (or both) of two independent reasons --
    `blocking_segments` (horizon-side, e.g. `["supercruise"]`) and
    `value_unavailable_reason` (value-side, e.g.
    "species value model not implemented"). Never dropped, never
    force-scored; kept separate from Recommendation/RejectedCandidate
    entirely so it can recover automatically once the missing input
    exists, without any change to candidate generation (design doc §1.1).

    `expected_value` is populated whenever Value could compute it, even
    if `blocking_segments` is non-empty (e.g. `mining_sell`) -- see
    design doc §1's Score-eligibility note: it's held here rather than
    discarded so a future SC estimate doesn't require recomputing Value."""

    action: str
    target: BioTarget | MiningTarget
    breakdown: dict[str, HorizonComponent]
    blocking_segments: list[str]
    reason: str
    expected_value: float | None = None
    value_unavailable_reason: str | None = None


def is_scoreable(
    blocking_segments: list[str],
    expected_value: float | None,
    value_unavailable_reason: str | None,
    action_horizon_seconds: float | None,
) -> bool:
    """docs/PHASE_2_3_HORIZON_VALUE_DESIGN_BASELINE_V0.1.md §1/§7: Phase
    2-3's Score-eligibility check, evaluated on the raw inputs (rather
    than an already-built IncompleteCandidate) so the pipeline can decide
    which DTO to build -- ActionCandidate or IncompleteCandidate -- from
    the result, instead of constructing one to find out it should have
    been the other. Deliberately not named anything Recommendation-shaped
    -- selecting a winner among scoreable candidates is Phase 2-4's
    `rank_candidates`/`select_recommendation`, not this function's job.

    `action_horizon_seconds > 0` (edge-case review, Phase 2-3 follow-up)
    guards against a calibrated segment summing to a non-positive
    duration -- `blocking_segments == []` only means no segment is
    `unavailable`, not that the total is a usable positive number."""
    return (
        blocking_segments == []
        and expected_value is not None
        and value_unavailable_reason is None
        and action_horizon_seconds is not None
        and action_horizon_seconds > 0
    )


def build_horizon(
    required_segments: Sequence[str], session: Session
) -> tuple[dict[str, TimeEstimate], bool, float | None]:
    """Assembles horizon_components for exactly the segment types a given
    action's horizon is composed of, and derives horizon_complete +
    action_horizon_seconds (None unless complete).

    This is the Phase 0-C "AHEの不完全なhorizonをActionCandidateへ伝播できる"
    exit criterion — how a horizon_complete=False candidate should
    ultimately be scored is not decided here (Phase 2, §12.4)."""
    components = {seg: estimate_segment(seg, None, session) for seg in required_segments}
    complete = all(c.status != "unavailable" for c in components.values())
    total_seconds = sum(c.seconds for c in components.values()) if complete else None
    return components, complete, total_seconds


@dataclass
class DataSource:
    """docs/PHASE_2_0_DESIGN_BASELINE_V0.1.md §2.5. Not populated anywhere
    yet — Phase 2-5's job (freshness/confidence composition retrofit).
    Defined now so `Recommendation` doesn't need a second DTO revision."""

    name: str
    observed_at: dt.datetime | None
    received_at: dt.datetime | None
    freshness: float | None


@dataclass
class ReasonFact:
    """docs/PHASE_2_0_DESIGN_BASELINE_V0.1.md §2.3. Not generated anywhere
    yet — Phase 2-5's job (retrofit into Horizon/Value/Confidence/Score).
    Defined now for the same reason as `DataSource` above."""

    factor: str
    effect: str  # "positive" | "negative"
    value: float
    comparison: float | None


@dataclass
class Recommendation:
    """docs/PHASE_2_4_RANKING_DESIGN_BASELINE_V0.1.md §5.1: the DTO for a
    candidate that has been ranked and selected (`select_recommendation`)
    or kept as a scored runner-up (`build_alternatives`) — reused as-is
    from docs/PHASE_2_0_DESIGN_BASELINE_V0.1.md §2.1, no intermediate
    type. `data_sources`/`reasons`/`narration` stay at their defaults in
    Phase 2-4 (Phase 2-5 populates them); `rejected` stays `[]` in Phase
    2-4 -- the canonical place for RejectedCandidate is
    `NextActionResponse.rejected`, not this field (§5.1/§5.3)."""

    action: str
    target: BioTarget | MiningTarget
    expected_value: float
    action_horizon_seconds: float
    score_per_hour: float
    confidence: float
    breakdown: dict[str, HorizonComponent]
    data_sources: list[DataSource] = field(default_factory=list)
    reasons: list[ReasonFact] = field(default_factory=list)
    rejected: list[RejectedCandidate] = field(default_factory=list)
    narration: str | None = None


@dataclass
class NextActionResponse:
    """docs/PHASE_2_4_RANKING_DESIGN_BASELINE_V0.1.md §5.3: top-level
    response DTO. `rejected` is new relative to
    docs/PHASE_2_0_DESIGN_BASELINE_V0.1.md §2.7 -- it's the canonical,
    response-level home for both `category="filter"` (Phase 2-2) and
    `category="score"` (Phase 2-4) RejectedCandidate entries, since a
    rejection reason belongs to the whole response's audit trail, not to
    any single Recommendation."""

    next_action: str | None
    recommendation: Recommendation | None
    alternatives: list[Recommendation]
    incomplete: list[IncompleteCandidate]
    rejected: list[RejectedCandidate]
    reason: str | None
