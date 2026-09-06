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

# Symmetric ("either direction") small-change band -- numerically the
# same constant as MATERIAL_DECREASE_RELATIVE_THRESHOLD, but a distinct
# concept: "unchanged" (Phase 2-6F-T3 §2.2) tests |relative_change|,
# while "material decrease" only ever tests the downward direction.
# Sharing the number is deliberate (reuse the one already-reviewed
# threshold rather than invent a second one), not a coincidence to be
# confused with the directional test.
UNCHANGED_ABS_RELATIVE_THRESHOLD = STABLE_MEDIAN_PRICE_CHANGE

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


# ---------------------------------------------------------------------------
# Phase 2-6F-T3: rigorous window-relative re-analysis.
#
# Fixes a real methodological flaw in compute_price_persistence() above:
# that function used the flat MAX_OBSERVATION_GAP (6h) as its tolerance
# for EVERY window, so a "5-minute" comparison could silently be matched
# against an observation up to 6 hours later. This section does NOT
# modify or replace compute_price_persistence()/its results -- both are
# kept, and this section's numbers are cross-referenced against them
# (docs/PHASE_2_6F_T3_..._DESIGN_BASELINE_V0.1.md §0/§7) so a real
# earlier finding is never silently overwritten, only superseded with
# the discrepancy stated openly.
# ---------------------------------------------------------------------------


def _median_p25_p75(values: list) -> tuple:
    """None,None,None for fewer than 4 points -- quartiles from a
    handful of samples would overstate precision the data doesn't
    support (median alone is still reported once >=1 point exists)."""
    if not values:
        return None, None, None
    if len(values) < 4:
        return statistics.median(values), None, None
    quartiles = statistics.quantiles(values, n=4, method="exclusive")
    return statistics.median(values), quartiles[0], quartiles[2]


@dataclass(frozen=True)
class PriceComparison:
    station_id: int
    commodity_name: str
    t0: dt.datetime
    t0_price: int
    window: dt.timedelta
    matched_observed_at: dt.datetime
    matched_price: int
    comparison_gap: dt.timedelta  # matched_observed_at - target; signed (early match is negative)


def _find_window_comparison(
    rows: list[MarketHistoricalObservation], t0_index: int, window: dt.timedelta
) -> MarketHistoricalObservation | None:
    """Phase 2-6F-T3 §1: valid only if |observed_at - target| <= window
    (tolerance scales with the window itself, not a flat constant) --
    e.g. target=T0+30min accepts a match up to 30min early or late, so
    an observation 150 minutes after target (the user's own worked
    example) is correctly rejected regardless of window size."""
    t0_row = rows[t0_index]
    target = _naive(t0_row.observed_at) + window
    candidates = [r for r in rows[t0_index + 1 :] if abs(_naive(r.observed_at) - target) <= window]
    if not candidates:
        return None
    return min(candidates, key=lambda r: abs(_naive(r.observed_at) - target))


def collect_price_comparisons(
    session: Session, window: dt.timedelta
) -> tuple[list[PriceComparison], int, int]:
    """Returns (comparisons, eligible_count, undefined_baseline_count).
    `eligible_count` counts every observation as a T0 candidate;
    `undefined_baseline_count` is those with t0_price<=0 (relative
    change undefined, excluded rather than guessed); the remainder
    without a comparison are implicitly censored (eligible_count -
    undefined_baseline_count - len(comparisons))."""
    comparisons: list[PriceComparison] = []
    eligible_count = 0
    undefined_baseline_count = 0
    for (station_id, commodity_name), rows in _rows_by_station_commodity(session).items():
        for i, t0_row in enumerate(rows):
            eligible_count += 1
            if t0_row.sell_price <= 0:
                undefined_baseline_count += 1
                continue
            match = _find_window_comparison(rows, i, window)
            if match is None:
                continue
            target = _naive(t0_row.observed_at) + window
            comparisons.append(
                PriceComparison(
                    station_id=station_id, commodity_name=commodity_name, t0=t0_row.observed_at,
                    t0_price=t0_row.sell_price, window=window, matched_observed_at=match.observed_at,
                    matched_price=match.sell_price, comparison_gap=_naive(match.observed_at) - target,
                )
            )
    return comparisons, eligible_count, undefined_baseline_count


def _material_decrease_within_window(
    rows: list[MarketHistoricalObservation], t0_index: int, window: dt.timedelta, threshold: float
) -> bool:
    """Distinct from the single point-in-time comparison used for
    material_decrease_at_window_rate: True if a material decrease is
    observed ANYWHERE in (T0, T0+window], not just at the matched T0+
    window snapshot -- a price that dipped and partially recovered by
    the exact window boundary still counts here (design doc §5's
    explicit "within t" vs "at t" distinction)."""
    t0_row = rows[t0_index]
    t0_price = t0_row.sell_price
    window_end = _naive(t0_row.observed_at) + window
    for later_row in rows[t0_index + 1 :]:
        observed_at = _naive(later_row.observed_at)
        if observed_at > window_end:
            break
        if _is_material_decrease(t0_price, later_row.sell_price, threshold):
            return True
    return False


@dataclass(frozen=True)
class WindowPriceStats:
    window: dt.timedelta
    eligible_count: int
    comparison_count: int
    undefined_baseline_count: int
    censored_count: int
    unchanged_rate: float | None
    decrease_rate: float | None
    median_relative_change: float | None
    p25_relative_change: float | None
    p75_relative_change: float | None
    material_decrease_at_window_rate: float | None
    material_decrease_within_window_rate: float | None
    median_observation_gap: dt.timedelta | None
    p25_observation_gap: dt.timedelta | None
    p75_observation_gap: dt.timedelta | None


def compute_window_price_stats(
    session: Session,
    window: dt.timedelta,
    material_threshold: float = MATERIAL_DECREASE_RELATIVE_THRESHOLD,
    unchanged_threshold: float = UNCHANGED_ABS_RELATIVE_THRESHOLD,
) -> WindowPriceStats:
    comparisons, eligible_count, undefined_baseline_count = collect_price_comparisons(session, window)
    comparison_count = len(comparisons)
    censored_count = eligible_count - undefined_baseline_count - comparison_count

    relative_changes = [(c.matched_price - c.t0_price) / c.t0_price for c in comparisons]
    unchanged_rate = (
        None if comparison_count == 0
        else sum(1 for r in relative_changes if abs(r) < unchanged_threshold) / comparison_count
    )
    decrease_rate = None if comparison_count == 0 else sum(1 for r in relative_changes if r < 0) / comparison_count
    median_change, p25_change, p75_change = _median_p25_p75(relative_changes)

    material_at_window = None
    if comparison_count > 0:
        hits = sum(1 for c in comparisons if _is_material_decrease(c.t0_price, c.matched_price, material_threshold))
        material_at_window = hits / comparison_count

    by_pair = _rows_by_station_commodity(session)
    within_window_eligible = 0
    within_window_hits = 0
    for (station_id, commodity_name), rows in by_pair.items():
        for i, t0_row in enumerate(rows[:-1]):
            if t0_row.sell_price <= 0:
                continue
            within_window_eligible += 1
            if _material_decrease_within_window(rows, i, window, material_threshold):
                within_window_hits += 1
    material_within_window = None if within_window_eligible == 0 else within_window_hits / within_window_eligible

    gaps = [abs(c.comparison_gap) for c in comparisons]
    median_gap, p25_gap, p75_gap = _median_p25_p75(gaps)

    return WindowPriceStats(
        window=window,
        eligible_count=eligible_count,
        comparison_count=comparison_count,
        undefined_baseline_count=undefined_baseline_count,
        censored_count=censored_count,
        unchanged_rate=unchanged_rate,
        decrease_rate=decrease_rate,
        median_relative_change=median_change,
        p25_relative_change=p25_change,
        p75_relative_change=p75_change,
        material_decrease_at_window_rate=material_at_window,
        material_decrease_within_window_rate=material_within_window,
        median_observation_gap=median_gap,
        p25_observation_gap=p25_gap,
        p75_observation_gap=p75_gap,
    )


@dataclass(frozen=True)
class ProfitWindowStats:
    window: dt.timedelta
    status: PersistenceMeasurementStatus
    eligible_count: int
    comparison_count: int
    profit_condition_persistence: float | None
    median_source_dest_time_diff: dt.timedelta | None


@dataclass(frozen=True)
class MatchedTradeOpportunity:
    source: MarketHistoricalObservation
    dest: MarketHistoricalObservation
    later_source: MarketHistoricalObservation
    later_dest: MarketHistoricalObservation
    source_dest_time_diff: dt.timedelta


def _iter_matched_trade_opportunities(session: Session, window: dt.timedelta) -> list[MatchedTradeOpportunity]:
    """Shared route-matching core for compute_profit_window_stats() and
    compute_margin_change_decomposition() -- one (source, dest) T0
    profitable opportunity, aligned within `window` of each other (§1's
    tolerance concept reused for source/dest alignment too), matched
    against its nearest later (source, dest) pair within the same
    window-relative tolerance from the target T0+window."""
    buy_rows = (
        session.query(MarketHistoricalObservation)
        .filter(MarketHistoricalObservation.buy_price.isnot(None))
        .order_by(MarketHistoricalObservation.commodity_name, MarketHistoricalObservation.observed_at)
        .all()
    )
    if not buy_rows:
        return []

    sell_by_commodity: dict[str, list[MarketHistoricalObservation]] = defaultdict(list)
    for row in (
        session.query(MarketHistoricalObservation)
        .order_by(MarketHistoricalObservation.commodity_name, MarketHistoricalObservation.observed_at)
        .all()
    ):
        sell_by_commodity[row.commodity_name].append(row)

    matches: list[MatchedTradeOpportunity] = []
    for source in buy_rows:
        for dest in sell_by_commodity.get(source.commodity_name, []):
            if dest.station_id == source.station_id:
                continue
            if abs(_naive(dest.observed_at) - _naive(source.observed_at)) > window:
                continue
            if dest.sell_price - source.buy_price <= 0:
                continue

            target = _naive(source.observed_at) + window
            later_sources = [
                r for r in buy_rows
                if r.station_id == source.station_id and r.commodity_name == source.commodity_name
                and abs(_naive(r.observed_at) - target) <= window
            ]
            later_dests = [
                r for r in sell_by_commodity.get(source.commodity_name, [])
                if r.station_id == dest.station_id and abs(_naive(r.observed_at) - target) <= window
            ]
            if not later_sources or not later_dests:
                continue

            matches.append(
                MatchedTradeOpportunity(
                    source=source, dest=dest,
                    later_source=min(later_sources, key=lambda r: abs(_naive(r.observed_at) - target)),
                    later_dest=min(later_dests, key=lambda r: abs(_naive(r.observed_at) - target)),
                    source_dest_time_diff=abs(_naive(dest.observed_at) - _naive(source.observed_at)),
                )
            )
    return matches


def compute_profit_window_stats(session: Session, window: dt.timedelta) -> ProfitWindowStats:
    """Same route definition as compute_profit_condition_persistence
    (source.buy_price known, dest is any other station's sell
    observation for the same commodity), but using the window-relative
    tolerance from §1 instead of the flat MAX_OBSERVATION_GAP, and
    explicitly recording the source/dest alignment time difference
    (design doc §2.3/§6). INSUFFICIENT whenever no row has buy_price --
    same structural gap as compute_profit_condition_persistence, not a
    new decision (docs/PHASE_2_6F_T1... §10, backfill Deferred)."""
    has_buy_price = (
        session.query(MarketHistoricalObservation).filter(MarketHistoricalObservation.buy_price.isnot(None)).first()
        is not None
    )
    if not has_buy_price:
        return ProfitWindowStats(
            window=window, status=PersistenceMeasurementStatus.INSUFFICIENT,
            eligible_count=0, comparison_count=0, profit_condition_persistence=None,
            median_source_dest_time_diff=None,
        )

    matches = _iter_matched_trade_opportunities(session, window)
    eligible_count = len(matches)
    comparison_count = eligible_count  # every returned match already has both later observations
    still_profitable_count = sum(1 for m in matches if m.later_dest.sell_price - m.later_source.buy_price > 0)
    time_diffs = [m.source_dest_time_diff for m in matches]

    persistence = None if comparison_count == 0 else still_profitable_count / comparison_count
    status = (
        PersistenceMeasurementStatus.INSUFFICIENT if comparison_count == 0 else PersistenceMeasurementStatus.COMPUTED
    )
    median_diff = statistics.median(time_diffs) if time_diffs else None
    return ProfitWindowStats(
        window=window, status=status, eligible_count=eligible_count, comparison_count=comparison_count,
        profit_condition_persistence=persistence, median_source_dest_time_diff=median_diff,
    )


@dataclass(frozen=True)
class MarginChangeDecomposition:
    status: PersistenceMeasurementStatus
    source_buy_only_changed_count: int
    dest_sell_only_changed_count: int
    both_changed_count: int
    neither_changed_count: int


def compute_margin_change_decomposition(session: Session, window: dt.timedelta) -> MarginChangeDecomposition:
    """Whether it was the source Buy price, the destination Sell price,
    both, or neither that moved between T0 and the window-relative
    later match (§2.4). "Changed" means any nonzero difference -- no
    separate materiality threshold is defined for this breakdown in the
    spec, so it stays binary (moved / didn't). INSUFFICIENT whenever no
    row has buy_price -- same structural gap as compute_profit_window_stats,
    not a new decision."""
    matches = _iter_matched_trade_opportunities(session, window)
    if not matches:
        has_buy_price = (
            session.query(MarketHistoricalObservation)
            .filter(MarketHistoricalObservation.buy_price.isnot(None))
            .first()
            is not None
        )
        return MarginChangeDecomposition(
            status=PersistenceMeasurementStatus.INSUFFICIENT if not has_buy_price else PersistenceMeasurementStatus.COMPUTED,
            source_buy_only_changed_count=0, dest_sell_only_changed_count=0,
            both_changed_count=0, neither_changed_count=0,
        )

    buy_only = sell_only = both = neither = 0
    for m in matches:
        buy_changed = m.later_source.buy_price != m.source.buy_price
        sell_changed = m.later_dest.sell_price != m.dest.sell_price
        if buy_changed and sell_changed:
            both += 1
        elif buy_changed:
            buy_only += 1
        elif sell_changed:
            sell_only += 1
        else:
            neither += 1

    return MarginChangeDecomposition(
        status=PersistenceMeasurementStatus.COMPUTED,
        source_buy_only_changed_count=buy_only, dest_sell_only_changed_count=sell_only,
        both_changed_count=both, neither_changed_count=neither,
    )
