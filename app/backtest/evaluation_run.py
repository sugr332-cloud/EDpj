"""Final evaluation orchestration & adoption decisions — Phase 2-6E.

Spec (docs/PHASE_2_6E_FINAL_EVALUATION_IMPLEMENTATION_BASELINE_V0.1.md).
Wires together 2-6A's replay sweep, 2-6B's volatility aggregation, 2-6C's
freshness aggregation, and 2-6D's journal coverage into one run, then
maps the results onto an adoption decision per axis
(decide_volatility_adoption/decide_freshness_adoption). No new
statistical logic is added here -- every number this module reports
comes from an existing 2-6A-D function.

Nothing in this module ever reads or writes
app.market.predictability's or app.scoring.confidence's threshold
constants: adoption is always a separate, human-reviewed commit (spec
§7), and the decision functions take only the evaluation *result* as
input, never the current threshold values themselves (spec §0.1) -- so
a decision can never be biased toward confirming whatever the current
config happens to be.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.backtest.freshness_evaluation import (
    FreshnessMonotonicityResult,
    aggregate_by_freshness_bucket,
    evaluate_freshness_monotonicity,
)
from app.backtest.journal_replay import (
    HorizonDiagnosticSample,
    collect_horizon_diagnostics,
    reconstruct_player_state_at,
)
from app.backtest.replay import ReplaySample, collect_replay_samples, generate_t0_checkpoints
from app.backtest.volatility_evaluation import (
    OrderingHypothesisResult,
    aggregate_by_volatility_class,
    evaluate_ordering_hypothesis,
)
from app.collectors.eddn_archive import StreamingHttpClient
from app.db.models.market import MarketSnapshot
from app.db.models.timing import TimingSample
from app.market.predictability import ensure_days_fetched_batch

# Operational constraint on archive fetch cost (docs/PHASE_2_5A...§1:
# ~60-112MB/day per station×commodity), not a statistically meaningful
# sample size.
MAX_EVALUATION_TARGETS = 20

# Doesn't affect archive fetch cost -- collect_replay_samples() only
# reads already-cached MarketHistoricalObservation per checkpoint, so a
# finer sweep is free (spec §1.2).
EVALUATION_T0_INTERVAL = dt.timedelta(hours=1)


@dataclass(frozen=True)
class EvaluationTarget:
    station_id: int
    commodity_name: str


def select_evaluation_targets(session: Session, max_targets: int = MAX_EVALUATION_TARGETS) -> list[EvaluationTarget]:
    """(station_id, commodity_name) pairs actually present in this
    player's own MarketSnapshot(source='journal') history, ordered by
    observation count -- not a galaxy-wide sample. `source='eddn'` rows
    are excluded: those are other players' concurrent observations, not
    markets this player is known to have visited (spec §1.1)."""
    rows = (
        session.query(
            MarketSnapshot.station_id,
            MarketSnapshot.commodity_name,
            func.count(MarketSnapshot.id).label("obs_count"),
        )
        .filter(MarketSnapshot.source == "journal")
        .group_by(MarketSnapshot.station_id, MarketSnapshot.commodity_name)
        .order_by(func.count(MarketSnapshot.id).desc())
        .limit(max_targets)
        .all()
    )
    return [EvaluationTarget(station_id=r[0], commodity_name=r[1]) for r in rows]


AdoptionDecision = Literal["GO", "CONDITIONAL_GO", "NO_GO", "INSUFFICIENT"]


def decide_volatility_adoption(result: OrderingHypothesisResult) -> AdoptionDecision:
    """Spec §3, coded so it's directly testable. Takes only the
    evaluation result -- never reads
    app.market.predictability.STABLE_MEDIAN_PRICE_CHANGE/
    MODERATE_MEDIAN_PRICE_CHANGE, so it cannot be biased toward
    confirming whatever the current thresholds happen to be (spec
    §0.1)."""
    if result.ordering_holds is None:
        return "INSUFFICIENT"
    if not result.ordering_holds:
        return "NO_GO"
    if result.stable_within_mae_threshold and result.volatile_exceeds_mae_threshold:
        return "GO"
    return "CONDITIONAL_GO"


def decide_freshness_adoption(result: FreshnessMonotonicityResult) -> AdoptionDecision:
    """Spec §4. Takes only the evaluation result -- never reads
    app.scoring.confidence.FRESHNESS_FULL_THRESHOLD/
    FRESHNESS_FLOOR_THRESHOLD/FRESHNESS_FLOOR (spec §0.1). No
    CONDITIONAL_GO branch: overall_monotonic=True only confirms the
    *structural* assumption (staler observations produce worse
    forecasts); proposing a specific curve shape or numeric threshold is
    explicitly a human review step (spec §4), not this function's job."""
    if result.overall_monotonic is None:
        return "INSUFFICIENT"
    return "GO" if result.overall_monotonic else "NO_GO"


@dataclass(frozen=True)
class JournalCoverageReport:
    state_reconstruction_coverage: float
    horizon_diagnostic_coverage: float
    diagnostics_by_segment_type: dict[str, list[HorizonDiagnosticSample]]


def _collect_journal_coverage(session: Session) -> JournalCoverageReport:
    """Reference-only report (spec §5) -- never consumed by
    decide_volatility_adoption()/decide_freshness_adoption()."""
    samples = session.query(TimingSample).all()
    if not samples:
        return JournalCoverageReport(
            state_reconstruction_coverage=0.0, horizon_diagnostic_coverage=0.0, diagnostics_by_segment_type={}
        )

    reconstructed_count = sum(1 for s in samples if reconstruct_player_state_at(session, s.start_time).fields)
    state_reconstruction_coverage = reconstructed_count / len(samples)

    diagnostics = collect_horizon_diagnostics(session)
    # supercruise is structurally always relative_error=None
    # (app/routing/time.py never calibrates it) -- excluded from the
    # denominator so it doesn't mechanically depress this coverage figure.
    non_supercruise = [d for d in diagnostics if d.segment_type != "supercruise"]
    horizon_diagnostic_coverage = (
        sum(1 for d in non_supercruise if d.relative_error is not None) / len(non_supercruise)
        if non_supercruise
        else 0.0
    )

    diagnostics_by_segment_type: dict[str, list[HorizonDiagnosticSample]] = {}
    for d in diagnostics:
        diagnostics_by_segment_type.setdefault(d.segment_type, []).append(d)

    return JournalCoverageReport(
        state_reconstruction_coverage=state_reconstruction_coverage,
        horizon_diagnostic_coverage=horizon_diagnostic_coverage,
        diagnostics_by_segment_type=diagnostics_by_segment_type,
    )


@dataclass(frozen=True)
class EvaluationRunReport:
    generated_at: dt.datetime
    targets: list[EvaluationTarget]
    target_sample_counts: dict[EvaluationTarget, int]
    volatility_by_window: dict[int, OrderingHypothesisResult]
    volatility_decision_by_window: dict[int, AdoptionDecision]
    freshness: FreshnessMonotonicityResult
    freshness_decision: AdoptionDecision
    journal_coverage: JournalCoverageReport


@dataclass(frozen=True)
class BacktestResults:
    volatility_by_window: dict[int, OrderingHypothesisResult]
    freshness: FreshnessMonotonicityResult
    target_sample_counts: dict[EvaluationTarget, int]


def compute_backtest_results(
    session: Session,
    client: StreamingHttpClient,
    now: dt.datetime,
    targets: list[EvaluationTarget],
    window_days_options: tuple[int, ...] = (7, 14, 30),
    t0_interval: dt.timedelta = EVALUATION_T0_INTERVAL,
    horizon: dt.timedelta = dt.timedelta(hours=1),
) -> BacktestResults:
    """The fetch/sweep/pool/aggregate core shared by Adoption Evaluation
    (run_evaluation, target = this player's own MarketSnapshot) and
    Model Validation (app.backtest.model_validation.run_model_validation,
    target = discovered from real EDDN coverage at stations this player
    has actually docked at) -- docs/PHASE_2_6E...v0.2 §13.1. Only target
    *selection* and what happens to the result (decide_*_adoption is
    Adoption-only) differ between the two callers; this function itself
    has no notion of which track is calling it."""
    max_window_days = max(window_days_options)
    fetch_window_start = now - dt.timedelta(days=max_window_days)
    fetch_dates = [
        (fetch_window_start + dt.timedelta(days=offset)).date()
        for offset in range((now.date() - fetch_window_start.date()).days + 1)
    ]
    # Batched across the whole target list, not one ensure_days_fetched()
    # call per target -- each date's archive file is downloaded/streamed
    # at most once regardless of how many targets share it (spec §14;
    # a real Model Validation run found 5 same-station targets over 7
    # days triggering 35 redundant downloads of the same 7 files before
    # this fix).
    ensure_days_fetched_batch(
        session, [(target.station_id, target.commodity_name) for target in targets], fetch_dates, client
    )

    volatility_by_window: dict[int, OrderingHypothesisResult] = {}
    target_sample_counts: dict[EvaluationTarget, int] = {}
    freshness_samples: list[ReplaySample] = []

    for window_days in window_days_options:
        window_start = now - dt.timedelta(days=window_days)
        checkpoints = generate_t0_checkpoints(window_start, now, t0_interval)

        window_samples: list[ReplaySample] = []
        window_target_counts: dict[EvaluationTarget, int] = {}
        for target in targets:
            collection = collect_replay_samples(
                session, target.station_id, target.commodity_name, checkpoints, window_days, horizon
            )
            window_samples.extend(collection.samples)
            window_target_counts[target] = len(collection.samples)

        volatility_stats = aggregate_by_volatility_class(window_samples)
        volatility_by_window[window_days] = evaluate_ordering_hypothesis(volatility_stats)

        # Freshness/target-count reporting uses the widest window's
        # samples -- age_at_t0()/forecast_error don't depend on
        # window_days at all (only volatility_class does, via
        # _compute_volatility_stats), and the widest window's T0 sweep
        # spans furthest back, giving the most complete picture of both.
        if window_days == max_window_days:
            freshness_samples = window_samples
            target_sample_counts = window_target_counts

    freshness_stats = aggregate_by_freshness_bucket(freshness_samples)
    freshness_result = evaluate_freshness_monotonicity(freshness_stats)

    return BacktestResults(
        volatility_by_window=volatility_by_window,
        freshness=freshness_result,
        target_sample_counts=target_sample_counts,
    )


def run_evaluation(
    session: Session,
    client: StreamingHttpClient,
    now: dt.datetime,
    targets: list[EvaluationTarget],
    window_days_options: tuple[int, ...] = (7, 14, 30),
    t0_interval: dt.timedelta = EVALUATION_T0_INTERVAL,
    horizon: dt.timedelta = dt.timedelta(hours=1),
) -> EvaluationRunReport:
    """Orchestrates spec §1-§6 (Adoption Evaluation track only). No new
    statistical logic -- every number comes from an existing 2-6A-D
    function. Never imports or references app.market.predictability's or
    app.scoring.confidence's threshold constants (spec §0.1/§7): this
    function reports evidence, it never decides or writes production
    values."""
    backtest = compute_backtest_results(session, client, now, targets, window_days_options, t0_interval, horizon)

    volatility_decision_by_window = {
        window_days: decide_volatility_adoption(result) for window_days, result in backtest.volatility_by_window.items()
    }
    freshness_decision = decide_freshness_adoption(backtest.freshness)

    journal_coverage = _collect_journal_coverage(session)

    return EvaluationRunReport(
        generated_at=now,
        targets=targets,
        target_sample_counts=backtest.target_sample_counts,
        volatility_by_window=backtest.volatility_by_window,
        volatility_decision_by_window=volatility_decision_by_window,
        freshness=backtest.freshness,
        freshness_decision=freshness_decision,
        journal_coverage=journal_coverage,
    )
