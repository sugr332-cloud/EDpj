"""Trade Market Persistence Analysis — Phase 2-6F-T1.

Spec (docs/SPECIFICATION_TRADE_MARKET_PERSISTENCE_AMENDMENT_V0.1.md,
docs/PHASE_TRADE_MARKET_PERSISTENCE_V0.1.md,
docs/PHASE_2_6F_T1_TRADE_MARKET_PERSISTENCE_DESIGN_BASELINE_V0.1.md).
Measures, from real historical `MarketHistoricalObservation` rows alone,
how long an observed price and a profitable Trade spread tend to persist
-- never assumes travel time, never treats a lack of observed decrease
as proof of stability (right-censoring), and never fabricates a result
when there isn't enough data (`INSUFFICIENT`, same principle as
app/backtest/formula_validation.py).

The "material decrease" threshold reuses app/market/predictability.py's
existing, already-reviewed `STABLE_MEDIAN_PRICE_CHANGE = 0.05` rather
than inventing a new number -- frozen here, before this module was ever
run against real data (design doc §3).

`compute_profit_condition_persistence` requires `buy_price` on the
source-side observation, which most existing MarketHistoricalObservation
rows never captured (design doc §2) -- this returns INSUFFICIENT
whenever no row has it, which is expected on real data today. It is
still implemented and tested against synthetic data so it needs no
further code changes once buy_price is backfilled.
"""
from __future__ import annotations

import datetime as dt
import statistics
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum

from sqlalchemy.orm import Session

from app.db.models.market import MarketHistoricalObservation
from app.market.predictability import MAX_OBSERVATION_GAP, STABLE_MEDIAN_PRICE_CHANGE

MATERIAL_DECREASE_RELATIVE_THRESHOLD = STABLE_MEDIAN_PRICE_CHANGE  # frozen, design doc §3

PERSISTENCE_WINDOWS_MINUTES = [5, 10, 15, 30, 60, 120]


def _naive(ts: dt.datetime) -> dt.datetime:
    # Same SQLite tz round-trip workaround as app/backtest/replay.py.
    return ts.replace(tzinfo=None) if ts.tzinfo is not None else ts


def _is_material_decrease(t0_price: int, later_price: int, threshold: float) -> bool | None:
    """None when t0_price <= 0 -- a relative decrease is undefined, not
    "no decrease". Never divides by zero."""
    if t0_price <= 0:
        return None
    return (t0_price - later_price) / t0_price >= threshold


def _rows_by_station_commodity(session: Session) -> dict[tuple[int, str], list[MarketHistoricalObservation]]:
    rows = (
        session.query(MarketHistoricalObservation)
        .order_by(
            MarketHistoricalObservation.station_id,
            MarketHistoricalObservation.commodity_name,
            MarketHistoricalObservation.observed_at,
        )
        .all()
    )
    by_pair: dict[tuple[int, str], list[MarketHistoricalObservation]] = defaultdict(list)
    for row in rows:
        by_pair[(row.station_id, row.commodity_name)].append(row)
    return by_pair


@dataclass(frozen=True)
class DataQualityReport:
    """Phase doc §8/§12 required deliverable fields not tied to any one
    persistence window -- describes the dataset itself, not a result."""

    total_observations: int
    unique_series_count: int  # unique (station_id, commodity_name) pairs
    observation_period_start: dt.datetime | None
    observation_period_end: dt.datetime | None
    median_observation_gap: dt.timedelta | None  # None only when no pair has >= 2 observations


def compute_data_quality_report(session: Session) -> DataQualityReport:
    by_pair = _rows_by_station_commodity(session)
    all_gaps: list[dt.timedelta] = []
    all_timestamps: list[dt.datetime] = []
    for rows in by_pair.values():
        all_timestamps.extend(_naive(r.observed_at) for r in rows)
        for prev, curr in zip(rows, rows[1:]):
            all_gaps.append(_naive(curr.observed_at) - _naive(prev.observed_at))

    return DataQualityReport(
        total_observations=len(all_timestamps),
        unique_series_count=len(by_pair),
        observation_period_start=min(all_timestamps) if all_timestamps else None,
        observation_period_end=max(all_timestamps) if all_timestamps else None,
        median_observation_gap=statistics.median(all_gaps) if all_gaps else None,
    )


@dataclass(frozen=True)
class PricePersistenceResult:
    window: dt.timedelta
    eligible_count: int
    comparison_count: int
    price_persistence: float | None
    material_decrease_count: int
    material_decrease_rate: float | None
    undefined_baseline_count: int  # t0_price <= 0, excluded from both numerator/denominator


def compute_price_persistence(
    session: Session,
    window: dt.timedelta,
    threshold: float = MATERIAL_DECREASE_RELATIVE_THRESHOLD,
    max_gap: dt.timedelta = MAX_OBSERVATION_GAP,
) -> PricePersistenceResult:
    """For every real observation (as a T0 candidate) of every
    (station_id, commodity_name) series, finds the nearest later
    observation within `(t0 + window, t0 + window + max_gap]` -- same
    tolerance-window search as app.backtest.replay.observe_actual_after,
    generalized across every series instead of one at a time. A T0 with
    no observation in that range is excluded from `comparison_count`
    (never treated as "price held")."""
    eligible_count = 0
    comparison_count = 0
    material_decrease_count = 0
    undefined_baseline_count = 0

    for rows in _rows_by_station_commodity(session).values():
        for i, t0_row in enumerate(rows):
            eligible_count += 1
            target = _naive(t0_row.observed_at) + window
            window_end = target + max_gap
            candidates = [
                r for r in rows[i + 1 :] if _naive(t0_row.observed_at) < _naive(r.observed_at) <= window_end
            ]
            if not candidates:
                continue
            nearest = min(candidates, key=lambda r: abs(_naive(r.observed_at) - target))
            decrease = _is_material_decrease(t0_row.sell_price, nearest.sell_price, threshold)
            if decrease is None:
                undefined_baseline_count += 1
                continue
            comparison_count += 1
            if decrease:
                material_decrease_count += 1

    price_persistence = None if comparison_count == 0 else 1 - material_decrease_count / comparison_count
    material_decrease_rate = None if comparison_count == 0 else material_decrease_count / comparison_count
    return PricePersistenceResult(
        window=window,
        eligible_count=eligible_count,
        comparison_count=comparison_count,
        price_persistence=price_persistence,
        material_decrease_count=material_decrease_count,
        material_decrease_rate=material_decrease_rate,
        undefined_baseline_count=undefined_baseline_count,
    )


@dataclass(frozen=True)
class TimeToDecreaseCase:
    station_id: int
    commodity_name: str
    t0: dt.datetime
    time_to_event: dt.timedelta
    censored: bool  # True: no material decrease found before the series' last observation


@dataclass(frozen=True)
class TimeToDecreaseSummary:
    cases: list[TimeToDecreaseCase]
    event_count: int  # decrease actually observed
    censored_count: int
    median_time_to_first_decrease: dt.timedelta | None  # over event_count cases only, None if 0


@dataclass(frozen=True)
class MaterialDecreaseEvent:
    """One real, individual material-decrease occurrence -- Phase
    2-6F-T2 (docs/PHASE_2_6F_T2_LARGE_PRICE_MOVEMENT_CHARACTERIZATION_
    DESIGN_BASELINE_V0.1.md §2.1). Kept as the shared, ungrouped record
    that both the time-to-decrease summary (this module) and the
    commodity/station breakdowns, demand correlation, and reversion
    analysis (2-6F-T2) are all built from -- one extraction pass, not
    duplicated scanning logic per downstream question."""

    station_id: int
    commodity_name: str
    t0: dt.datetime
    t0_price: int
    t0_demand: int
    event_observed_at: dt.datetime
    event_price: int
    event_demand: int
    relative_decrease: float
    time_to_event: dt.timedelta
    gap_before_event: dt.timedelta  # event_observed_at minus the observation immediately before it


@dataclass(frozen=True)
class CensoredCase:
    """A T0 that never saw a qualifying material decrease before its
    series' last observation -- right-censored there, per spec §4, not
    treated as proof of indefinite stability."""

    station_id: int
    commodity_name: str
    t0: dt.datetime
    time_to_censoring: dt.timedelta  # last observation in the series minus t0


def collect_material_decrease_events(
    session: Session, threshold: float = MATERIAL_DECREASE_RELATIVE_THRESHOLD
) -> tuple[list[MaterialDecreaseEvent], list[CensoredCase]]:
    """For each T0 with at least one later observation in its series,
    scans forward chronologically for the first later observation
    satisfying the material-decrease criterion. A T0 with no qualifying
    later observation before its series' last observation becomes a
    CensoredCase instead of a MaterialDecreaseEvent -- no event actually
    occurred there, so it must never be represented as one."""
    events: list[MaterialDecreaseEvent] = []
    censored: list[CensoredCase] = []
    for (station_id, commodity_name), rows in _rows_by_station_commodity(session).items():
        for i, t0_row in enumerate(rows[:-1]):
            if t0_row.sell_price <= 0:
                continue  # undefined relative decrease, excluded (not fabricated as "no decrease")
            found = None
            found_index = None
            for j, later_row in enumerate(rows[i + 1 :], start=i + 1):
                if _is_material_decrease(t0_row.sell_price, later_row.sell_price, threshold):
                    found = later_row
                    found_index = j
                    break
            if found is None:
                last_row = rows[-1]
                censored.append(
                    CensoredCase(
                        station_id=station_id, commodity_name=commodity_name, t0=t0_row.observed_at,
                        time_to_censoring=_naive(last_row.observed_at) - _naive(t0_row.observed_at),
                    )
                )
                continue
            preceding = rows[found_index - 1]
            events.append(
                MaterialDecreaseEvent(
                    station_id=station_id,
                    commodity_name=commodity_name,
                    t0=t0_row.observed_at,
                    t0_price=t0_row.sell_price,
                    t0_demand=t0_row.demand,
                    event_observed_at=found.observed_at,
                    event_price=found.sell_price,
                    event_demand=found.demand,
                    relative_decrease=(t0_row.sell_price - found.sell_price) / t0_row.sell_price,
                    time_to_event=_naive(found.observed_at) - _naive(t0_row.observed_at),
                    gap_before_event=_naive(found.observed_at) - _naive(preceding.observed_at),
                )
            )
    return events, censored


def compute_time_to_first_material_decrease(
    session: Session, threshold: float = MATERIAL_DECREASE_RELATIVE_THRESHOLD
) -> TimeToDecreaseSummary:
    """Same result shape as before collect_material_decrease_events()
    existed -- this is now a thin summary over its output, no re-scan."""
    events, censored = collect_material_decrease_events(session, threshold)
    cases = [
        TimeToDecreaseCase(
            station_id=e.station_id, commodity_name=e.commodity_name, t0=e.t0,
            time_to_event=e.time_to_event, censored=False,
        )
        for e in events
    ] + [
        TimeToDecreaseCase(
            station_id=c.station_id, commodity_name=c.commodity_name, t0=c.t0,
            time_to_event=c.time_to_censoring, censored=True,
        )
        for c in censored
    ]

    event_times = [e.time_to_event for e in events]
    median = statistics.median(event_times) if event_times else None
    return TimeToDecreaseSummary(
        cases=cases,
        event_count=len(events),
        censored_count=len(censored),
        median_time_to_first_decrease=median,
    )


@dataclass(frozen=True)
class GroupMoveSummary:
    """Phase 2-6F-T2 §2.2: a group (one commodity, or one station) only
    appears here if at least one MaterialDecreaseEvent actually occurred
    for it -- a group with zero events is simply absent, never
    synthesized as a zero-event row (same convention as
    freshness_evaluation.aggregate_by_freshness_bucket)."""

    key: str | int
    event_count: int
    median_relative_decrease: float
    median_time_to_event: dt.timedelta


def _summarize_events(events: list[MaterialDecreaseEvent], key_fn) -> dict:
    by_key: dict = defaultdict(list)
    for event in events:
        by_key[key_fn(event)].append(event)
    return {
        key: GroupMoveSummary(
            key=key,
            event_count=len(group),
            median_relative_decrease=statistics.median(e.relative_decrease for e in group),
            median_time_to_event=statistics.median(e.time_to_event for e in group),
        )
        for key, group in by_key.items()
    }


def summarize_events_by_commodity(events: list[MaterialDecreaseEvent]) -> dict[str, GroupMoveSummary]:
    return _summarize_events(events, lambda e: e.commodity_name)


def summarize_events_by_station(events: list[MaterialDecreaseEvent]) -> dict[int, GroupMoveSummary]:
    return _summarize_events(events, lambda e: e.station_id)


@dataclass(frozen=True)
class DemandCorrelationResult:
    """Directional only (§2.3 of the design doc) -- a full correlation
    coefficient would overstate precision the likely-small real event
    count doesn't support."""

    event_count: int
    demand_decreased_count: int
    demand_increased_count: int
    demand_unchanged_count: int


def compute_demand_change_at_events(events: list[MaterialDecreaseEvent]) -> DemandCorrelationResult:
    decreased = sum(1 for e in events if e.event_demand < e.t0_demand)
    increased = sum(1 for e in events if e.event_demand > e.t0_demand)
    unchanged = sum(1 for e in events if e.event_demand == e.t0_demand)
    return DemandCorrelationResult(
        event_count=len(events), demand_decreased_count=decreased,
        demand_increased_count=increased, demand_unchanged_count=unchanged,
    )


class ReversionOutcome(str, Enum):
    REVERTED = "REVERTED"
    PERSISTED = "PERSISTED"
    CENSORED = "CENSORED"


@dataclass(frozen=True)
class ReversionCase:
    event: MaterialDecreaseEvent
    outcome: ReversionOutcome
    time_to_reversion: dt.timedelta | None  # only set when outcome is REVERTED


# The inverse of MATERIAL_DECREASE_RELATIVE_THRESHOLD (0.05): if a 5%
# drop counts as "a material decrease", recovering to 95% of the
# pre-event price counts as "back to normal" -- reusing the same frozen
# number rather than inventing an independent threshold.
REVERSION_RECOVERY_RATIO = 1 - MATERIAL_DECREASE_RELATIVE_THRESHOLD


def compute_price_reversion(
    session: Session,
    events: list[MaterialDecreaseEvent],
    reversion_window: dt.timedelta = dt.timedelta(hours=24),
    recovery_ratio: float = REVERSION_RECOVERY_RATIO,
) -> list[ReversionCase]:
    """For each event, looks only at observations strictly after
    `event_observed_at` and at or before `event_observed_at +
    reversion_window` (never later -- future leakage guard). REVERTED if
    any of those observations reaches `>= recovery_ratio * t0_price`.
    Otherwise: PERSISTED if at least one later observation exists in
    that window (price stayed down, actually observed), or CENSORED if
    none exists at all (no evidence either way -- never assumed to mean
    "stayed down forever")."""
    by_pair = _rows_by_station_commodity(session)
    cases: list[ReversionCase] = []
    for event in events:
        rows = by_pair[(event.station_id, event.commodity_name)]
        window_end = _naive(event.event_observed_at) + reversion_window
        later_rows = [r for r in rows if _naive(event.event_observed_at) < _naive(r.observed_at) <= window_end]
        recovery_target = recovery_ratio * event.t0_price

        reverted_row = next((r for r in later_rows if r.sell_price >= recovery_target), None)
        if reverted_row is not None:
            cases.append(
                ReversionCase(
                    event=event, outcome=ReversionOutcome.REVERTED,
                    time_to_reversion=_naive(reverted_row.observed_at) - _naive(event.event_observed_at),
                )
            )
        elif later_rows:
            cases.append(ReversionCase(event=event, outcome=ReversionOutcome.PERSISTED, time_to_reversion=None))
        else:
            cases.append(ReversionCase(event=event, outcome=ReversionOutcome.CENSORED, time_to_reversion=None))
    return cases


def compute_buy_side_movement_status(session: Session) -> PersistenceMeasurementStatus:
    """Whether buy-side (source station Buy price) movement can be
    characterized at all. Same structural gap as
    compute_profit_condition_persistence (design doc §2.5) -- `buy_price`
    was never captured for most existing rows (backfill Deferred,
    docs/PHASE_2_6F_T1... §10). INSUFFICIENT here is not a new decision,
    just the same one applied to a second metric."""
    has_buy_price = (
        session.query(MarketHistoricalObservation)
        .filter(MarketHistoricalObservation.buy_price.isnot(None))
        .first()
        is not None
    )
    return PersistenceMeasurementStatus.COMPUTED if has_buy_price else PersistenceMeasurementStatus.INSUFFICIENT


class PersistenceMeasurementStatus(str, Enum):
    """Distinct from formula_validation.GateVerdict -- that enum judges
    whether a *formula* clears the 60% accuracy bar; this one only says
    whether the persistence *measurement itself* could be computed at
    all. A low persistence rate is still a valid COMPUTED result, not
    INSUFFICIENT."""

    COMPUTED = "COMPUTED"
    INSUFFICIENT = "INSUFFICIENT"


@dataclass(frozen=True)
class ProfitConditionPersistenceResult:
    window: dt.timedelta
    status: PersistenceMeasurementStatus
    eligible_count: int
    comparison_count: int
    persistence: float | None


def compute_profit_condition_persistence(
    session: Session,
    window: dt.timedelta,
    max_gap: dt.timedelta = MAX_OBSERVATION_GAP,
) -> ProfitConditionPersistenceResult:
    """A "Trade opportunity" is one (source_station, dest_station,
    commodity) route: source.buy_price known, dest observation is any
    row for the same commodity at a different station, aligned within
    `max_gap` of the source observation (treated as "the same T0 market
    snapshot" -- reuses the existing tolerance concept, doesn't invent a
    new one). `profit_condition` holds when dest.sell_price - source.buy_price > 0.
    INSUFFICIENT whenever no observation has `buy_price` at all -- design
    doc §2 (real data today has none, this is expected, not a bug)."""
    buy_rows = (
        session.query(MarketHistoricalObservation)
        .filter(MarketHistoricalObservation.buy_price.isnot(None))
        .order_by(MarketHistoricalObservation.commodity_name, MarketHistoricalObservation.observed_at)
        .all()
    )
    if not buy_rows:
        return ProfitConditionPersistenceResult(
            window=window, status=PersistenceMeasurementStatus.INSUFFICIENT,
            eligible_count=0, comparison_count=0, persistence=None,
        )

    sell_by_commodity: dict[str, list[MarketHistoricalObservation]] = defaultdict(list)
    for row in (
        session.query(MarketHistoricalObservation)
        .order_by(MarketHistoricalObservation.commodity_name, MarketHistoricalObservation.observed_at)
        .all()
    ):
        sell_by_commodity[row.commodity_name].append(row)

    eligible_count = 0
    comparison_count = 0
    still_profitable_count = 0

    for source in buy_rows:
        for dest in sell_by_commodity.get(source.commodity_name, []):
            if dest.station_id == source.station_id:
                continue
            if abs(_naive(dest.observed_at) - _naive(source.observed_at)) > max_gap:
                continue
            if dest.sell_price - source.buy_price <= 0:
                continue  # not a T0 profitable opportunity at all

            eligible_count += 1
            target = _naive(source.observed_at) + window
            window_end = target + max_gap

            later_sources = [
                r
                for r in buy_rows
                if r.station_id == source.station_id
                and r.commodity_name == source.commodity_name
                and _naive(source.observed_at) < _naive(r.observed_at) <= window_end
            ]
            later_dests = [
                r
                for r in sell_by_commodity.get(source.commodity_name, [])
                if r.station_id == dest.station_id and _naive(dest.observed_at) < _naive(r.observed_at) <= window_end
            ]
            if not later_sources or not later_dests:
                continue

            later_source = min(later_sources, key=lambda r: abs(_naive(r.observed_at) - target))
            later_dest = min(later_dests, key=lambda r: abs(_naive(r.observed_at) - target))
            comparison_count += 1
            if later_dest.sell_price - later_source.buy_price > 0:
                still_profitable_count += 1

    persistence = None if comparison_count == 0 else still_profitable_count / comparison_count
    status = (
        PersistenceMeasurementStatus.INSUFFICIENT if comparison_count == 0 else PersistenceMeasurementStatus.COMPUTED
    )
    return ProfitConditionPersistenceResult(
        window=window, status=status, eligible_count=eligible_count, comparison_count=comparison_count,
        persistence=persistence,
    )
