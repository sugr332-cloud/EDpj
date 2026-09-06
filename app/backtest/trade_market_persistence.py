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


def compute_time_to_first_material_decrease(
    session: Session, threshold: float = MATERIAL_DECREASE_RELATIVE_THRESHOLD
) -> TimeToDecreaseSummary:
    """For each T0 with at least one later observation in its series,
    scans forward chronologically for the first later observation
    satisfying the material-decrease criterion. If none is found before
    the series' last observation, the case is right-censored there --
    never treated as proof the price would never have dropped (spec
    §4: "a price with no observed decrease is not treated as proof of
    indefinite stability")."""
    cases: list[TimeToDecreaseCase] = []
    for (station_id, commodity_name), rows in _rows_by_station_commodity(session).items():
        for i, t0_row in enumerate(rows[:-1]):
            if t0_row.sell_price <= 0:
                continue  # undefined relative decrease, excluded (not fabricated as "no decrease")
            found = None
            for later_row in rows[i + 1 :]:
                if _is_material_decrease(t0_row.sell_price, later_row.sell_price, threshold):
                    found = later_row
                    break
            if found is not None:
                cases.append(
                    TimeToDecreaseCase(
                        station_id=station_id, commodity_name=commodity_name, t0=t0_row.observed_at,
                        time_to_event=_naive(found.observed_at) - _naive(t0_row.observed_at), censored=False,
                    )
                )
            else:
                last_row = rows[-1]
                cases.append(
                    TimeToDecreaseCase(
                        station_id=station_id, commodity_name=commodity_name, t0=t0_row.observed_at,
                        time_to_event=_naive(last_row.observed_at) - _naive(t0_row.observed_at), censored=True,
                    )
                )

    events = [c.time_to_event for c in cases if not c.censored]
    median = statistics.median(events) if events else None
    return TimeToDecreaseSummary(
        cases=cases,
        event_count=len(events),
        censored_count=sum(1 for c in cases if c.censored),
        median_time_to_first_decrease=median,
    )


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
