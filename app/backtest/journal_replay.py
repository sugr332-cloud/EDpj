"""Player state replay & horizon diagnostics — Phase 2-6D.

Spec (docs/PHASE_2_6D_PLAYER_STATE_REPLAY_IMPLEMENTATION_BASELINE_V0.1.md).
Scope was narrowed during design after discovering that CargoState (held
cargo quantity) has no historical time series anywhere in this project --
it's only ever a full-replacement snapshot from the *current* Cargo.json,
never reconstructed from journal events. Since mining Candidate
Generation and Value both depend on CargoState, this module does NOT
attempt Candidate Generation, Value, Score, Ranking, or a full
Recommendation replay (spec §0.1). It reconstructs only what journal
events alone can faithfully rebuild -- position/docked state/ship ID --
and cross-references the Action Horizon Estimator against real recorded
segment durations as a diagnostic, not a Go/No-Go metric (spec §3.1).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models.journal import JournalEvent
from app.db.models.timing import TimingSample
from app.journal import events as ev
from app.routing.time import TimeEstimate, estimate_segment
from app.state.reducer import reduce_events


@dataclass(frozen=True)
class ReplayPlayerState:
    """PlayerState reconstructed purely from journal events bounded to
    t0. Deliberately does NOT carry cargo/credits/fuel/on_foot -- those
    come only from Status.json/Cargo.json, live snapshots with no
    historical time series (spec §0.1). Kept as its own type rather than
    reusing app.state.reducer.ReducedPlayerState (which has
    cargo_rows/source_status fields) so "this replay never had cargo
    data at all" can never be confused with "cargo was checked and
    found empty"."""

    t0: dt.datetime
    fields: dict  # only keys reduce_events() ever sets: current_system,
    # current_system_address, current_body_id, current_body_name,
    # current_station_id, current_station_name, docked, landed,
    # current_ship_id


def reconstruct_player_state_at(session: Session, t0: dt.datetime) -> ReplayPlayerState:
    """Reuses app.state.reducer.reduce_events() unchanged, over only the
    STATE_RELEVANT_EVENTS with `timestamp <= t0` -- no new reducer logic.
    The `<= t0` bound is a SQL-level filter (a bind parameter), not a
    Python-side datetime subtraction, so this needs none of
    app/backtest/replay.py's `_naive()` SQLite tz round-trip handling."""
    events = (
        session.query(JournalEvent)
        .filter(JournalEvent.event_type.in_(ev.STATE_RELEVANT_EVENTS))
        .filter(JournalEvent.timestamp <= t0)
        .all()
    )
    return ReplayPlayerState(t0=t0, fields=reduce_events(events))


@dataclass(frozen=True)
class HorizonDiagnosticSample:
    segment_type: str
    start_time: dt.datetime
    actual_duration_seconds: float
    estimate: TimeEstimate
    relative_error: float | None  # None whenever estimate.status != "estimated" -- never 0 or interpolated


def collect_horizon_diagnostics(session: Session) -> list[HorizonDiagnosticSample]:
    """Cross-references every existing TimingSample (Phase 0-B/0-C's own
    collected ground truth) against app.routing.time.estimate_segment()'s
    CURRENT output for that segment_type.

    This is a diagnostic, not an independent leakage-free accuracy
    metric: estimate_segment() reads whatever CalibrationModel exists
    right now, fit on Phase 2-1's own fit/eval split -- not bounded to
    each sample's own start_time. A TimingSample that happened to be in
    the model's *fit* split will look artificially accurate here; one in
    the *eval* split is consistent with (not independent of)
    CalibrationModel.median_absolute_error, which remains the
    authoritative, leakage-free figure. `supercruise` always yields
    `unavailable` (app/routing/time.py never calibrates it), so its
    relative_error is always None -- expected, not an error."""
    diagnostics: list[HorizonDiagnosticSample] = []
    for sample in session.query(TimingSample).all():
        estimate = estimate_segment(sample.segment_type, context=None, session=session)
        relative_error = None
        if estimate.status == "estimated" and estimate.seconds is not None:
            relative_error = abs(estimate.seconds - sample.duration_seconds) / sample.duration_seconds
        diagnostics.append(
            HorizonDiagnosticSample(
                segment_type=sample.segment_type,
                start_time=sample.start_time,
                actual_duration_seconds=sample.duration_seconds,
                estimate=estimate,
                relative_error=relative_error,
            )
        )
    return diagnostics
