"""Model Validation track — Phase 2-6E v0.2.

Spec (docs/PHASE_2_6E_FINAL_EVALUATION_IMPLEMENTATION_BASELINE_V0.1.md
§13). Answers a different question from Adoption Evaluation
(app.backtest.evaluation_run): not "should we adopt these thresholds for
this player's real markets" but "does the model's statistical
assumption (volatility class vs. forecast error ordering, freshness
monotonicity) hold on real EDDN data at all". Evaluation Run #1 found
this player's own MarketSnapshot(source='journal') empty, which blocks
Adoption Evaluation entirely but says nothing about whether the model
itself is sound -- this module exists to answer that second question
independently.

Neither Spansh's static Station table nor the EDDN archive itself
indexes "which station trades which commodity" -- so target discovery
is two-staged: candidate station_ids come from this player's own
Journal (real, confirmed-valid MarketIDs from Docked events), then each
candidate is discovery-scanned for one real archived day to find out
what it actually reports to EDDN (spec §13.2).

Results from this module NEVER feed app.backtest.evaluation_run's
decide_volatility_adoption()/decide_freshness_adoption() and
ModelValidationReport has no *_decision field -- confirming the model's
assumption holds on some real market says nothing about whether it's
safe to adopt for THIS player's markets (spec §13.3). Adoption is
exclusively Adoption Evaluation's decision.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.backtest.evaluation_run import (
    EVALUATION_T0_INTERVAL,
    EvaluationTarget,
    compute_backtest_results,
)
from app.backtest.freshness_evaluation import FreshnessMonotonicityResult
from app.backtest.volatility_evaluation import OrderingHypothesisResult
from app.collectors.eddn import MalformedEddnMessage, parse_commodity_message
from app.collectors.eddn_archive import StreamingHttpClient, iter_commodity_day
from app.db.models.journal import JournalEvent
from app.journal import events as ev

# Same cost-bound reasoning as app.backtest.evaluation_run.MAX_EVALUATION_TARGETS
# (docs/PHASE_2_5A...§1: ~60-112MB/day per station×commodity) -- kept as
# an independent constant since the two tracks may need different caps
# in the future, even though they start at the same value (spec §13.2
# point 5).
MAX_MODEL_VALIDATION_TARGETS = 20

# Activity gate for select_diverse_model_validation_targets() (spec §15.2)
# -- how many times this commodity was reported that day, not how much
# its price moved. An explicit placeholder, not a statistically derived
# value.
MIN_DISCOVERY_OBSERVATIONS = 3


@dataclass(frozen=True)
class CommodityDiscovery:
    observation_count: int
    latest_demand: int  # from the last matching row seen during the scan, "most recent wins" (same convention as MarketLatest)
    latest_supply: int


@dataclass(frozen=True)
class StationDiscoveryResult:
    station_id: int
    discovery_date: dt.date
    commodities: dict[str, CommodityDiscovery] = field(default_factory=dict)
    # Empty dict = DISCOVERY_EMPTY: this station WAS scanned and
    # genuinely had zero EDDN reports on discovery_date -- distinct from
    # "never scanned" (no StationDiscoveryResult exists for it at all),
    # the same "zero rows vs. never fetched" distinction
    # app.market.predictability.MarketHistoricalFetchLog already makes
    # (spec §13.2 point 3).


def candidate_station_ids(session: Session) -> list[int]:
    """Distinct MarketIDs from this player's own Docked journal events --
    the only station IDs we can be confident are real, valid MarketIDs
    without an external station index (spec §13.2 point 1)."""
    rows = session.query(JournalEvent.payload).filter(JournalEvent.event_type == ev.DOCKED).all()
    station_ids = {payload["MarketID"] for (payload,) in rows if payload.get("MarketID") is not None}
    return sorted(station_ids)


def discover_commodities_at_station(
    station_id: int, discovery_date: dt.date, client: StreamingHttpClient
) -> StationDiscoveryResult:
    """Single-station convenience wrapper around
    discover_commodities_at_stations() -- kept for callers/tests that
    only care about one station. Prefer discover_commodities_at_stations()
    when checking multiple candidates for the same discovery_date: this
    function alone would re-download that day's full archive once per
    call, which is wasteful when select_model_validation_targets() has
    several candidate stations to check on the same day."""
    return discover_commodities_at_stations([station_id], discovery_date, client)[0]


def discover_commodities_at_stations(
    station_ids: list[int], discovery_date: dt.date, client: StreamingHttpClient
) -> list[StationDiscoveryResult]:
    """Scans exactly one archived day ONCE, across ALL commodities,
    checking every station in `station_ids` in the same pass -- there is
    no station×commodity index anywhere (spec §13.2 point 2), so a
    full-day scan is the only way to learn what a station actually
    trades, and re-scanning the same day per-station would multiply
    archive bandwidth for no reason when there are several candidates
    (spec §13.2 point 1 can produce more than one candidate station).
    Malformed envelopes are skipped, same policy as the live EDDN
    subscriber (app/collectors/eddn.py) and
    app.collectors.eddn_archive.fetch_commodity_observations. Returns
    one StationDiscoveryResult per input station_id, in the same order,
    even if that station never appeared that day (DISCOVERY_EMPTY,
    spec §13.2 point 3)."""
    targets = set(station_ids)
    counts_by_station: dict[int, dict[str, int]] = {sid: {} for sid in targets}
    latest_by_station: dict[int, dict[str, tuple[int, int]]] = {sid: {} for sid in targets}  # commodity -> (demand, supply)
    for envelope in iter_commodity_day(discovery_date, client):
        message = envelope.get("message")
        if not isinstance(message, dict):
            continue
        market_id = message.get("marketId")
        if market_id not in targets:
            continue
        try:
            rows = parse_commodity_message(message, received_at=dt.datetime.now(dt.timezone.utc))
        except MalformedEddnMessage:
            continue
        counts = counts_by_station[market_id]
        latest = latest_by_station[market_id]
        for row in rows:
            name = row["commodity_name"]
            counts[name] = counts.get(name, 0) + 1
            latest[name] = (row["demand"], row.get("supply", 0))
    return [
        StationDiscoveryResult(
            station_id=sid,
            discovery_date=discovery_date,
            commodities={
                name: CommodityDiscovery(
                    observation_count=count,
                    latest_demand=latest_by_station[sid][name][0],
                    latest_supply=latest_by_station[sid][name][1],
                )
                for name, count in counts_by_station[sid].items()
            },
        )
        for sid in station_ids
    ]


@dataclass(frozen=True)
class ModelValidationTarget:
    station_id: int
    commodity_name: str
    discovery_observation_count: int  # ranking input only, not an analysis sample count


def select_model_validation_targets(
    session: Session,
    client: StreamingHttpClient,
    now: dt.datetime,
    max_targets: int = MAX_MODEL_VALIDATION_TARGETS,
) -> tuple[list[ModelValidationTarget], list[StationDiscoveryResult]]:
    """discovery_date = (now - 1 day).date() -- "today" may not be
    archived yet (docs/PHASE_2_5A...§4: iter_commodity_day yields
    nothing for a not-yet-generated day, not an error), so yesterday is
    virtually certain to already exist (spec §13.2 point 2). Ranking:
    discovery observation count descending, tie-broken by
    (station_id, commodity_name) ascending for full reproducibility --
    never reordered after the fact based on which result "looks better"
    (spec §13.2 point 4)."""
    discovery_date = (now - dt.timedelta(days=1)).date()
    discoveries = discover_commodities_at_stations(candidate_station_ids(session), discovery_date, client)

    candidates: list[ModelValidationTarget] = []
    for discovery in discoveries:
        for commodity_name, info in discovery.commodities.items():
            candidates.append(
                ModelValidationTarget(
                    station_id=discovery.station_id,
                    commodity_name=commodity_name,
                    discovery_observation_count=info.observation_count,
                )
            )
    candidates.sort(key=lambda t: (-t.discovery_observation_count, t.station_id, t.commodity_name))

    return candidates[:max_targets], discoveries


def select_diverse_model_validation_targets(
    session: Session,
    client: StreamingHttpClient,
    now: dt.datetime,
    max_targets: int = MAX_MODEL_VALIDATION_TARGETS,
    min_observations: int = MIN_DISCOVERY_OBSERVATIONS,
) -> tuple[list[ModelValidationTarget], list[StationDiscoveryResult]]:
    """Diverse Market Target Selection (spec §15) -- an alternative to
    select_model_validation_targets() ("Baseline Selection", kept
    unchanged and still the default for run_model_validation()). A real
    5-target/14-day run using Baseline Selection found all 5 targets
    landing on one station (its commodities dominate by sheer report
    count), and 96.7% of forecast_error samples came back exactly zero
    -- not because the model validated well, but because the selected
    commodities were structurally near-static (supply=0 at that
    station, meaning their sell_price is closer to a nominal meanPrice
    than a real traded price).

    This function takes only two axes, NEITHER of which is price/
    volatility/forecast_error -- selecting on those would make target
    selection depend on the very quantity 2-6B/2-6C are trying to
    measure, a circular selection bias (spec §15.2):

    1. Station diversity: round-robin across candidate stations, so one
       high-traffic station can't fill the whole target list.
    2. An activity gate that looks only at reporting frequency and
       stock, never price: `observation_count >= min_observations`
       (this commodity was reported often enough that day to have
       real data, not a proxy for "prices moved a lot") and
       `latest_supply > 0` (predict_naive_persistence() forecasts
       `sell_price`, which is only meaningful when the station actually
       stocks the commodity -- `demand` is kept on CommodityDiscovery
       as a diagnostic but is NOT filtered on, since demand describes
       buyer interest, not whether sell_price reflects real trade).

    No randomness: round-robin is itself a deterministic stratification
    (station_id ascending, then observation count descending /
    commodity_name ascending as the within-station tie-break -- the same
    secondary ordering Baseline Selection already uses), reproducible
    without seed management."""
    discovery_date = (now - dt.timedelta(days=1)).date()
    discoveries = discover_commodities_at_stations(candidate_station_ids(session), discovery_date, client)

    per_station_eligible: dict[int, list[ModelValidationTarget]] = {}
    for discovery in discoveries:
        eligible = [
            ModelValidationTarget(discovery.station_id, name, info.observation_count)
            for name, info in discovery.commodities.items()
            if info.observation_count >= min_observations and info.latest_supply > 0
        ]
        eligible.sort(key=lambda t: (-t.discovery_observation_count, t.commodity_name))
        per_station_eligible[discovery.station_id] = eligible

    selected: list[ModelValidationTarget] = []
    station_order = sorted(per_station_eligible)  # station_id ascending -- deterministic
    round_index = 0
    while len(selected) < max_targets:
        added_this_round = False
        for station_id in station_order:
            candidates_for_station = per_station_eligible[station_id]
            if round_index < len(candidates_for_station):
                selected.append(candidates_for_station[round_index])
                added_this_round = True
                if len(selected) == max_targets:
                    break
        if not added_this_round:
            break
        round_index += 1

    return selected, discoveries


@dataclass(frozen=True)
class ModelValidationReport:
    generated_at: dt.datetime
    discovery_date: dt.date
    station_discoveries: list[StationDiscoveryResult]
    targets: list[ModelValidationTarget]
    target_sample_counts: dict[EvaluationTarget, int]  # same review rationale as EvaluationRunReport's field
    volatility_by_window: dict[int, OrderingHypothesisResult]
    freshness: FreshnessMonotonicityResult
    # Deliberately no *_decision field -- Model Validation never produces
    # an adoption decision (spec §13.3). Only
    # app.backtest.evaluation_run.EvaluationRunReport may.


def run_model_validation(
    session: Session,
    client: StreamingHttpClient,
    now: dt.datetime,
    window_days_options: tuple[int, ...] = (7, 14, 30),
    t0_interval: dt.timedelta = EVALUATION_T0_INTERVAL,
    horizon: dt.timedelta = dt.timedelta(hours=1),
    max_targets: int = MAX_MODEL_VALIDATION_TARGETS,
    select_targets_fn=select_model_validation_targets,
) -> ModelValidationReport:
    """Discovers targets (spec §13.2), then reuses the exact same
    fetch/sweep/pool/aggregate core Adoption Evaluation uses
    (compute_backtest_results) -- never calls decide_volatility_adoption()/
    decide_freshness_adoption() (spec §13.3).

    `select_targets_fn` defaults to select_model_validation_targets()
    (Baseline Selection) so existing callers/results are unaffected;
    pass select_diverse_model_validation_targets() explicitly to use
    Diverse Market Target Selection instead (spec §15.5). Both share the
    same (session, client, now, max_targets) call shape."""
    targets, discoveries = select_targets_fn(session, client, now, max_targets)
    backtest_targets = [EvaluationTarget(t.station_id, t.commodity_name) for t in targets]

    backtest = compute_backtest_results(session, client, now, backtest_targets, window_days_options, t0_interval, horizon)

    return ModelValidationReport(
        generated_at=now,
        discovery_date=(now - dt.timedelta(days=1)).date(),
        station_discoveries=discoveries,
        targets=targets,
        target_sample_counts=backtest.target_sample_counts,
        volatility_by_window=backtest.volatility_by_window,
        freshness=backtest.freshness,
    )
