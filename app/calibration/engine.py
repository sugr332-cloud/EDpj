"""Calibration Engine — Phase 2-1.

Spec (IMPLEMENTATION_SPEC_V0.2.md §6.1/§6.4, docs/PHASE_2_0_DESIGN_BASELINE_V0.1.md §1.1):
fits one `CalibrationModel` row per segment_type from `timing_samples`,
using a chronological 70/30 fit/eval split that never divides a single
play session (a session = one journal file, `start_file_name`) across the
boundary — a random split is explicitly forbidden.

`supercruise` is never calibrated here (IMPLEMENTATION_SPEC_V0.2.md §5.3):
candidate-specific SC time stays `unavailable` regardless of how much
duration_seconds telemetry exists — see app/routing/time.py.
"""
from __future__ import annotations

import statistics
from typing import Sequence

from sqlalchemy.orm import Session

from app.calibration.metrics import median_absolute_error, median_signed_error, r_squared, validation_status
from app.calibration.models import CalibrationResult
from app.db.models.calibration import CalibrationModel
from app.db.models.timing import TimingSample
from app.db.upsert import upsert_preserve_columns

FIT_RATIO = 0.7

CALIBRATED_SEGMENT_TYPES = (
    "jump",
    "dock",
    "undock",
    "descent",
    "ascent",
    "mining_cycle",
    "bio_sample",
)


def chronological_session_split(samples: Sequence[TimingSample]) -> tuple[list[TimingSample], list[TimingSample]]:
    """Groups samples by session (`start_file_name`), orders sessions
    chronologically by their first sample's `start_time`, and assigns
    whole sessions to fit until roughly FIT_RATIO of all samples are
    covered — the remaining sessions go to eval. A session is never split
    across the two."""
    if not samples:
        return [], []

    ordered = sorted(samples, key=lambda s: (s.start_time, s.start_file_name, s.start_line_number))
    session_order: list[str] = []
    sessions: dict[str, list[TimingSample]] = {}
    for s in ordered:
        if s.start_file_name not in sessions:
            sessions[s.start_file_name] = []
            session_order.append(s.start_file_name)
        sessions[s.start_file_name].append(s)

    target_fit_count = round(len(ordered) * FIT_RATIO)
    fit: list[TimingSample] = []
    eval_: list[TimingSample] = []
    cumulative = 0
    for session_key in session_order:
        session_samples = sessions[session_key]
        if cumulative < target_fit_count:
            fit.extend(session_samples)
            cumulative += len(session_samples)
        else:
            eval_.extend(session_samples)
    return fit, eval_


def fit_segment(segment_type: str, session: Session) -> CalibrationResult:
    """Fits and persists one segment_type's CalibrationModel row. Never
    raises for lack of data — sample_count_fit/eval simply come back 0 and
    validation_status="insufficient" (app/routing/time.py maps that to
    `unavailable`, never a guessed number)."""
    rows = session.query(TimingSample).filter(TimingSample.segment_type == segment_type).all()
    fit_rows, eval_rows = chronological_session_split(rows)

    if not fit_rows:
        result = CalibrationResult(
            segment_type=segment_type,
            seconds=None,
            sample_count_fit=0,
            sample_count_eval=0,
            median_absolute_error=None,
            median_signed_error=None,
            r_squared=None,
            validation_status="insufficient",
        )
    else:
        predicted = statistics.median(r.duration_seconds for r in fit_rows)
        if not eval_rows:
            result = CalibrationResult(
                segment_type=segment_type,
                seconds=predicted,
                sample_count_fit=len(fit_rows),
                sample_count_eval=0,
                median_absolute_error=None,
                median_signed_error=None,
                r_squared=None,
                validation_status="insufficient",
            )
        else:
            eval_durations = [r.duration_seconds for r in eval_rows]
            mae = median_absolute_error(predicted, eval_durations)
            signed = median_signed_error(predicted, eval_durations)
            result = CalibrationResult(
                segment_type=segment_type,
                seconds=predicted,
                sample_count_fit=len(fit_rows),
                sample_count_eval=len(eval_rows),
                median_absolute_error=mae,
                median_signed_error=signed,
                r_squared=r_squared(predicted, eval_durations),
                validation_status=validation_status(len(eval_rows), mae, signed),
            )

    _store(session, result)
    return result


def fit_all(session: Session) -> dict[str, CalibrationResult]:
    return {segment_type: fit_segment(segment_type, session) for segment_type in CALIBRATED_SEGMENT_TYPES}


def _store(session: Session, result: CalibrationResult) -> None:
    import datetime as dt

    row = {
        "segment_type": result.segment_type,
        "seconds": result.seconds,
        "sample_count_fit": result.sample_count_fit,
        "sample_count_eval": result.sample_count_eval,
        "median_absolute_error": result.median_absolute_error,
        "median_signed_error": result.median_signed_error,
        "r_squared": result.r_squared,
        "validation_status": result.validation_status,
        "fitted_at": dt.datetime.now(dt.timezone.utc),
    }
    # A refit always replaces the previous result outright (no column is
    # preserved) -- unlike app/collectors/eddn.py's body_bio_signals
    # upsert, there's nothing here that should survive a fresh fit.
    upsert_preserve_columns(session, CalibrationModel, [row], ["segment_type"], preserve_columns=set())
    session.commit()
