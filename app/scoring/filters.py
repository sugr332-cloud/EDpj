"""Deterministic filters — Phase 2-2.

Spec (docs/PHASE_2_2_CANDIDATE_GENERATION_DESIGN_BASELINE_V0.1.md §6).

Only jump-range reachability is implemented as an actual post-generation
filter here:

  - `demand <= 0` and unresolved station/system identity are already
    excluded at *generation* time (app/mining/candidates.py,
    app/bio/candidates.py query only `demand > 0` rows and skip targets
    they can't identify) — there is no candidate left by the time this
    filter runs to reject for those reasons. Per design doc §10, a
    candidate that was never generated is not recorded as a
    `RejectedCandidate` either — there's nothing to record.
  - Landing-pad compatibility is not implemented: there is no ship/
    loadout data source anywhere in the codebase yet. Rather than
    fabricate a check against data that doesn't exist, this filter is
    simply absent until a ship/loadout table exists.
  - Jump-range reachability itself cannot be computed either:
    `laden_jump_range` (IMPLEMENTATION_SPEC_V0.2.md §9.1, FSD range from
    Loadout module stats) is Routing/Time Service work that hasn't been
    built. Per §22 ("判定不能な場合は除外せずconfidenceを下げる"), the
    correct behavior when it's indeterminate is to reject nothing — so
    today `apply_filters` is a documented pass-through, not a fabricated
    pass/fail. It becomes a real filter the moment `app/routing/range.py`
    exists, without changing the pipeline shape.
"""
from __future__ import annotations

from app.scoring.models import DraftCandidate, RejectedCandidate


def apply_filters(candidates: list[DraftCandidate]) -> tuple[list[DraftCandidate], list[RejectedCandidate]]:
    """Returns (passed, rejected). See module docstring for why this
    currently always passes every candidate through."""
    return list(candidates), []
