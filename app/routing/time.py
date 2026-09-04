"""Action Horizon Estimator (AHE) — segment-level time estimation.

Spec (IMPLEMENTATION_SPEC_V0.2.md §6.5): `estimate_segment` returns a
`TimeEstimate` per segment_type and never fabricates a value. `status` is
one of `measured` / `estimated` / `unavailable`; an `unavailable` result
always carries `seconds=None` and `confidence=None` (§26 — never fill
missing data with a guess).

`supercruise` ALWAYS returns `unavailable`, regardless of how much
`duration_seconds` telemetry exists in `timing_samples` for it. This is
deliberate, not a missing feature: current data sources (Journal alone)
cannot determine a *candidate-specific* SC travel distance (no SC
trajectory/position telemetry, no reliable start-position), so neither
`arrival_dist_from_star_ls` nor a global median duration can be used to
predict a specific candidate's SC time without distorting Unified
Scoring's candidate-to-candidate comparison — see
IMPLEMENTATION_SPEC_V0.2.md §5.3 and commits a58e8c1/de22ce9 for the full
reasoning. This is a data-source limitation, not a permanent design
constraint: once a data source for real SC travel distance exists, this
function can be extended to return `estimated` (§6.5/§14.4).

Phase 0-C scope only: this module does not decide how
`ActionCandidate.confidence` aggregates per-segment confidences, and does
not decide how Unified Scoring treats a candidate whose horizon is
incomplete — both are deferred to Phase 2 (§12.3/§12.4).
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Literal, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.timing import TimingSample

TimeEstimateStatus = Literal["measured", "estimated", "unavailable"]

# Reuses the ~20 samples target already established for jump/dock/undock/
# descent/ascent/mining_cycle/bio_sample calibration (IMPLEMENTATION_SPEC_V0.2.md
# §6.1/§6.4) as the measured/estimated boundary — not a new number invented
# for this module.
MEASURED_SAMPLE_THRESHOLD = 20

# Per-segment confidence values, not the final ActionCandidate.confidence
# aggregation (that formula is deferred to Phase 2 — see module docstring).
# Reuses the confidence-tier philosophy already in IMPLEMENTATION_SPEC_V0.2.md
# §12.3 (1.00/0.75/0.50/<0.50): a pure timing measurement alone — with no
# corroborating market/static-data freshness — is capped at the 0.75 tier
# even with ample samples.
MEASURED_CONFIDENCE = 0.75
ESTIMATED_CONFIDENCE_FLOOR = 0.20
ESTIMATED_CONFIDENCE_CEILING = 0.50

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


def _estimated_confidence(sample_count: int) -> float:
    """Linearly scales confidence within the 'estimated' tier by sample
    count, staying below the 'measured' tier's floor."""
    span = ESTIMATED_CONFIDENCE_CEILING - ESTIMATED_CONFIDENCE_FLOOR
    fraction = min(sample_count, MEASURED_SAMPLE_THRESHOLD) / MEASURED_SAMPLE_THRESHOLD
    return round(ESTIMATED_CONFIDENCE_FLOOR + span * fraction, 2)


def _summarize(segment_type: str, durations: Sequence[float]) -> TimeEstimate:
    """Pure summarization of already-fetched durations — kept separate
    from estimate_segment() so it's testable without a DB session."""
    if not durations:
        return TimeEstimate(
            segment_type=segment_type,
            status="unavailable",
            seconds=None,
            confidence=None,
            basis="no observed samples",
        )

    sample_count = len(durations)
    seconds = statistics.median(durations)

    if sample_count >= MEASURED_SAMPLE_THRESHOLD:
        return TimeEstimate(
            segment_type=segment_type,
            status="measured",
            seconds=seconds,
            confidence=MEASURED_CONFIDENCE,
            basis=f"observed sample_count={sample_count}, median",
        )

    return TimeEstimate(
        segment_type=segment_type,
        status="estimated",
        seconds=seconds,
        confidence=_estimated_confidence(sample_count),
        basis=f"observed sample_count={sample_count} (< {MEASURED_SAMPLE_THRESHOLD}), median",
    )


def estimate_segment(segment_type: str, context: dict | None, session: Session) -> TimeEstimate:
    """Returns the best available TimeEstimate for a given segment_type.

    `context` is accepted (unused today) to keep this signature stable for
    when a real SC-distance data source lets `supercruise` estimates
    become candidate-specific (§14.4) — at that point `context` would
    carry the candidate's target/position info. `session` is a practical
    addition beyond IMPLEMENTATION_SPEC_V0.2.md §6.5's 2-argument
    pseudocode, needed to query `timing_samples`.
    """
    if segment_type == "supercruise":
        return TimeEstimate(
            segment_type=segment_type,
            status="unavailable",
            seconds=None,
            confidence=None,
            basis=SUPERCRUISE_UNAVAILABLE_BASIS,
        )

    durations = session.scalars(
        select(TimingSample.duration_seconds).where(TimingSample.segment_type == segment_type)
    ).all()
    return _summarize(segment_type, durations)
