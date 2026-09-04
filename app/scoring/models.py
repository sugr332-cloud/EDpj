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

from dataclasses import dataclass
from typing import Sequence

from sqlalchemy.orm import Session

from app.routing.time import TimeEstimate, estimate_segment


@dataclass
class ActionCandidate:
    action: str
    target: dict | None
    expected_value: float
    action_horizon_seconds: float | None
    horizon_components: dict[str, TimeEstimate]
    horizon_complete: bool
    score_per_hour: float | None
    confidence: float
    reason: str


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
