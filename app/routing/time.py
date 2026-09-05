"""Action Horizon Estimator (AHE) — segment-level time estimation.

Spec (IMPLEMENTATION_SPEC_V0.2.md §6.5, docs/PHASE_2_0_DESIGN_BASELINE_V0.1.md):
`estimate_segment` returns a `TimeEstimate` per segment_type and never
fabricates a value. `status` is one of `measured` / `estimated` /
`unavailable`; an `unavailable` result always carries `seconds=None` and
`confidence=None` (§26 — never fill missing data with a guess).

`measured` is not produced by any code path here — it's reserved for a
value directly observed for the specific action being scored right now
(not applicable to a statistical estimate from historical calibration).
Everything the Calibration Engine (app/calibration/engine.py) produces is
`estimated`, regardless of how many samples it was fit from or whether its
held-out eval validation passed — sample count and validation quality are
diagnostic metadata on the stored `CalibrationModel` row, not a promotion
path to `measured` (per review — see app/db/models/calibration.py).

`supercruise` ALWAYS returns `unavailable`, regardless of how much
`duration_seconds` telemetry exists in `timing_samples` for it (it is
never calibrated at all — see app/calibration/engine.py's
CALIBRATED_SEGMENT_TYPES). This is deliberate, not a missing feature:
current data sources (Journal alone) cannot determine a
*candidate-specific* SC travel distance (no SC trajectory/position
telemetry, no reliable start-position), so neither
`arrival_dist_from_star_ls` nor a global median duration can be used to
predict a specific candidate's SC time without distorting Unified
Scoring's candidate-to-candidate comparison — see
IMPLEMENTATION_SPEC_V0.2.md §5.3 and commits a58e8c1/de22ce9 for the full
reasoning. This is a data-source limitation, not a permanent design
constraint: once a data source for real SC travel distance exists, this
function can be extended to return `estimated` (§6.5/§14.4).

Phase 0-C/2-0 scope only: this module does not decide how
`Recommendation.confidence` aggregates per-segment confidences, and does
not decide how Unified Scoring treats a candidate whose horizon is
incomplete — both are deferred to later Phase 2 steps
(docs/PHASE_2_0_DESIGN_BASELINE_V0.1.md §5, §3/§4).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from app.db.models.calibration import CalibrationModel

TimeEstimateStatus = Literal["measured", "estimated", "unavailable"]

# Component-confidence constants (docs/PHASE_2_0_DESIGN_BASELINE_V0.1.md §1.1/§5).
# Not the final Recommendation.confidence aggregation formula — that's a
# later Phase 2 step. MEASURED_CONFIDENCE is unused today (see module
# docstring); UNAVAILABLE_CONFIDENCE is reserved for a future explicit
# fallback policy (Option B) and is not applied anywhere yet.
MEASURED_CONFIDENCE = 1.00
ESTIMATED_CONFIDENCE = 0.85
UNAVAILABLE_CONFIDENCE = 0.60

SUPERCRUISE_UNAVAILABLE_BASIS = (
    "candidate-specific SC travel distance is not obtainable from current data "
    "sources (Journal has no SC trajectory/position telemetry); "
    "see IMPLEMENTATION_SPEC_V0.2.md §5.3"
)


@dataclass(frozen=True)
class TimeEstimate:
    segment_type: str
    status: TimeEstimateStatus
    seconds: float | None
    confidence: float | None
    basis: str


# docs/PHASE_2_0_DESIGN_BASELINE_V0.1.md §1.2: this satisfies the
# Explainability spec's HorizonComponent shape exactly, so Phase 2 reuses
# it under that name rather than defining a duplicate class.
HorizonComponent = TimeEstimate


def _unavailable(segment_type: str, basis: str) -> TimeEstimate:
    return TimeEstimate(segment_type=segment_type, status="unavailable", seconds=None, confidence=None, basis=basis)


def estimate_segment(segment_type: str, context: dict | None, session: Session) -> TimeEstimate:
    """Returns the best available TimeEstimate for a given segment_type,
    read from the stored `CalibrationModel` row (app/calibration/engine.py
    computes and persists these; this function does not fit anything
    itself).

    `context` is accepted (unused today) to keep this signature stable for
    when a real SC-distance data source lets `supercruise` estimates
    become candidate-specific (§14.4) — at that point `context` would
    carry the candidate's target/position info. `session` is a practical
    addition beyond IMPLEMENTATION_SPEC_V0.2.md §6.5's 2-argument
    pseudocode, needed to query `calibration_models`.
    """
    if segment_type == "supercruise":
        return _unavailable(segment_type, SUPERCRUISE_UNAVAILABLE_BASIS)

    model = session.query(CalibrationModel).filter_by(segment_type=segment_type).one_or_none()
    if model is None or model.sample_count_fit == 0:
        return _unavailable(segment_type, "no observed samples")

    if model.sample_count_eval == 0:
        return _unavailable(
            segment_type, f"insufficient eval data to validate (fit={model.sample_count_fit}, eval=0)"
        )

    basis = (
        f"calibrated: fit={model.sample_count_fit}, eval={model.sample_count_eval}, "
        f"validation={model.validation_status}, mae={model.median_absolute_error:.2f}"
    )
    return TimeEstimate(
        segment_type=segment_type,
        status="estimated",
        seconds=model.seconds,
        confidence=ESTIMATED_CONFIDENCE,
        basis=basis,
    )
