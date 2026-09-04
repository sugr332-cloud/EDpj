"""Phase 0-B: extracts timing samples (start event -> end event) from an
ordered journal event stream.

Spec (IMPLEMENTATION_SPEC_V0.2 section 5):
  - "start event -> end event = timing sample"; incomplete pairs (no
    matching end, or an interrupting event in between) are never used for
    model training — they're dropped, not guessed at.
  - Segment types: jump, supercruise, dock, undock, descent, ascent,
    bio_sample, mining_cycle, route_plot.
  - Supercruise is the special case: its start is SupercruiseEntry *or*
    FSDJump (arrival is already supercruise — SupercruiseEntry normally
    doesn't fire after a jump), and a sample only counts toward the
    *distance* model if, after SupercruiseExit, a Docked or ApproachBody
    is reached before the next FSDJump/SupercruiseEntry. No fixed 120s
    filter. `distance_ls` itself is read from Docked's `DistFromStarLS`
    when present and left `None` otherwise — never estimated.
  - route_plot: Phase 0 does not attempt to reconstruct history; only a
    complete *forward* NavRoute execution (every leg flown in order, no
    NavRouteClear/deviation in between) is stored as a sample, with no
    distance/detour_factor computed yet (that needs Phase 1's static
    system coordinates).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Callable, Iterable

from app.journal import events as ev
from app.journal.types import TimestampedEvent


@dataclass(frozen=True)
class TimingSampleData:
    segment_type: str
    start_file_name: str
    start_line_number: int
    end_file_name: str
    end_line_number: int
    start_time: dt.datetime
    end_time: dt.datetime
    duration_seconds: float
    distance_ls: float | None = None
    valid_for_distance_model: bool = False
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class RoutePlotSampleData:
    navroute_file_name: str
    navroute_line_number: int
    systems: list[str]
    completed_at: dt.datetime
    leg_arrivals: list[dict]


def _build_sample(
    segment_type: str,
    start: TimestampedEvent,
    end: TimestampedEvent,
    *,
    distance_ls: float | None = None,
    valid_for_distance_model: bool = False,
    extra: dict | None = None,
) -> TimingSampleData:
    return TimingSampleData(
        segment_type=segment_type,
        start_file_name=start.file_name,
        start_line_number=start.line_number,
        end_file_name=end.file_name,
        end_line_number=end.line_number,
        start_time=start.timestamp,
        end_time=end.timestamp,
        duration_seconds=(end.timestamp - start.timestamp).total_seconds(),
        distance_ls=distance_ls,
        valid_for_distance_model=valid_for_distance_model,
        extra=extra or {},
    )


def _pair_simple(
    events: Iterable[TimestampedEvent],
    segment_type: str,
    is_start: Callable[[TimestampedEvent], bool],
    is_end: Callable[[TimestampedEvent], bool],
    is_interrupt: Callable[[TimestampedEvent], bool] = lambda e: False,
) -> list[TimingSampleData]:
    """Generic start->end pairing for segments with two distinct event
    types. A new start supersedes (drops) an unmatched previous start; an
    interrupt event also drops an open, unmatched start."""
    samples: list[TimingSampleData] = []
    open_start: TimestampedEvent | None = None
    for e in events:
        if is_start(e):
            open_start = e
            continue
        if open_start is not None:
            if is_end(e):
                samples.append(_build_sample(segment_type, open_start, e))
                open_start = None
            elif is_interrupt(e):
                open_start = None
    return samples


def _pair_consecutive(
    events: Iterable[TimestampedEvent],
    segment_type: str,
    is_target: Callable[[TimestampedEvent], bool],
    is_interrupt: Callable[[TimestampedEvent], bool],
    same_group: Callable[[TimestampedEvent, TimestampedEvent], bool] = lambda a, b: True,
) -> list[TimingSampleData]:
    """Pairs consecutive occurrences of the same repeating event (mining
    cycles, bio samples) as long as no interrupt breaks the streak and
    (optionally) both events belong to the same group (e.g. same
    species)."""
    samples: list[TimingSampleData] = []
    previous: TimestampedEvent | None = None
    for e in events:
        if is_target(e):
            if previous is not None and same_group(previous, e):
                samples.append(_build_sample(segment_type, previous, e))
            previous = e
            continue
        if previous is not None and is_interrupt(e):
            previous = None
    return samples


def extract_jump_samples(events: Iterable[TimestampedEvent]) -> list[TimingSampleData]:
    return _pair_simple(
        events,
        "jump",
        is_start=lambda e: e.event_type == ev.START_JUMP and e.payload.get("JumpType") == "Hyperspace",
        is_end=lambda e: e.event_type == ev.FSD_JUMP,
    )


def extract_supercruise_samples(events: Iterable[TimestampedEvent]) -> list[TimingSampleData]:
    samples: list[TimingSampleData] = []
    open_start: TimestampedEvent | None = None
    pending: tuple[TimestampedEvent, TimestampedEvent] | None = None

    def resolve(eligible: bool, distance_ls: float | None) -> None:
        nonlocal pending
        assert pending is not None
        start, end = pending
        samples.append(
            _build_sample("supercruise", start, end, distance_ls=distance_ls, valid_for_distance_model=eligible)
        )
        pending = None

    for e in events:
        is_departure = e.event_type in (ev.FSD_JUMP, ev.SUPERCRUISE_ENTRY)

        if pending is not None:
            if is_departure:
                resolve(eligible=False, distance_ls=None)
            elif e.event_type == ev.DOCKED:
                resolve(eligible=True, distance_ls=e.payload.get("DistFromStarLS"))
            elif e.event_type == ev.APPROACH_BODY:
                resolve(eligible=True, distance_ls=e.payload.get("DistFromStarLS"))

        if is_departure:
            open_start = e  # supersedes any unmatched previous open_start
        elif open_start is not None and e.event_type == ev.SUPERCRUISE_EXIT:
            pending = (open_start, e)
            open_start = None

    if pending is not None:
        resolve(eligible=False, distance_ls=None)

    return samples


def extract_dock_samples(events: Iterable[TimestampedEvent]) -> list[TimingSampleData]:
    return _pair_simple(
        events,
        "dock",
        is_start=lambda e: e.event_type == ev.DOCKING_GRANTED,
        is_end=lambda e: e.event_type == ev.DOCKED,
        is_interrupt=lambda e: e.event_type in (ev.DOCKING_CANCELLED, ev.DOCKING_TIMEOUT, ev.DOCKING_DENIED),
    )


def extract_undock_samples(events: Iterable[TimestampedEvent]) -> list[TimingSampleData]:
    return _pair_simple(
        events,
        "undock",
        is_start=lambda e: e.event_type == ev.UNDOCKED,
        is_end=lambda e: e.event_type == ev.SUPERCRUISE_ENTRY,
        is_interrupt=lambda e: e.event_type in (ev.DOCKED, ev.FSD_JUMP),
    )


def extract_descent_samples(events: Iterable[TimestampedEvent]) -> list[TimingSampleData]:
    return _pair_simple(
        events,
        "descent",
        is_start=lambda e: e.event_type == ev.APPROACH_BODY,
        is_end=lambda e: e.event_type == ev.TOUCHDOWN,
        is_interrupt=lambda e: e.event_type in (ev.LIFTOFF, ev.SUPERCRUISE_ENTRY, ev.FSD_JUMP, ev.DOCKED, ev.LEAVE_BODY),
    )


def extract_ascent_samples(events: Iterable[TimestampedEvent]) -> list[TimingSampleData]:
    return _pair_simple(
        events,
        "ascent",
        is_start=lambda e: e.event_type == ev.LIFTOFF,
        is_end=lambda e: e.event_type in (ev.LEAVE_BODY, ev.SUPERCRUISE_ENTRY),
        is_interrupt=lambda e: e.event_type in (ev.TOUCHDOWN, ev.DOCKED, ev.FSD_JUMP),
    )


def extract_mining_cycle_samples(events: Iterable[TimestampedEvent]) -> list[TimingSampleData]:
    return _pair_consecutive(
        events,
        "mining_cycle",
        is_target=lambda e: e.event_type == ev.MINING_REFINED,
        is_interrupt=lambda e: e.event_type in (ev.DOCKED, ev.FSD_JUMP, ev.SUPERCRUISE_ENTRY),
    )


def extract_bio_sample_samples(events: Iterable[TimestampedEvent]) -> list[TimingSampleData]:
    def same_species(a: TimestampedEvent, b: TimestampedEvent) -> bool:
        return a.payload.get("Genus") == b.payload.get("Genus") and a.payload.get("Species") == b.payload.get(
            "Species"
        )

    return _pair_consecutive(
        events,
        "bio_sample",
        is_target=lambda e: e.event_type == ev.SCAN_ORGANIC,
        is_interrupt=lambda e: e.event_type in (ev.LIFTOFF, ev.FSD_JUMP, ev.SUPERCRUISE_ENTRY, ev.DOCKED),
        same_group=same_species,
    )


def extract_route_plot_samples(
    events: Iterable[TimestampedEvent], navroute_data: dict | None = None
) -> list[RoutePlotSampleData]:
    """Only a NavRoute event whose plotted systems can actually be read
    (from `navroute_data` — the current NavRoute.json, correlated by the
    caller the same way Market.json is correlated to Docked) and whose
    every leg is then flown in order, uninterrupted, produces a sample.

    Backfill only ever has the *current* NavRoute.json, so `navroute_data`
    can only possibly describe the *last* `NavRoute` event in the stream —
    earlier NavRoute events in history have no recoverable route content
    (Frontier writes the leg list to NavRoute.json, not the journal line)
    and are skipped rather than guessed at. Live collection (Phase 1+)
    reads NavRoute.json at the time of each event and won't have this
    limitation.
    """
    events = list(events)
    last_navroute_index = max(
        (i for i, e in enumerate(events) if e.event_type == ev.NAV_ROUTE), default=None
    )

    samples: list[RoutePlotSampleData] = []
    active_navroute_event: TimestampedEvent | None = None
    planned_systems: list[str] = []
    leg_index = 0
    leg_arrivals: list[dict] = []

    for i, e in enumerate(events):
        if e.event_type == ev.NAV_ROUTE_CLEAR:
            active_navroute_event = None
            planned_systems = []
            leg_arrivals = []
            leg_index = 0
            continue

        if e.event_type == ev.NAV_ROUTE:
            active_navroute_event = None
            planned_systems = []
            leg_index = 0
            leg_arrivals = []
            if i == last_navroute_index and navroute_data:
                route = navroute_data.get("Route") or []
                systems = [leg.get("StarSystem") for leg in route if leg.get("StarSystem")]
                # A NavRoute.json's own route usually starts with the
                # system the player was already in when they plotted it —
                # that leg isn't something FSDJump will ever report
                # arriving at, so drop it before pairing against jumps.
                if len(systems) >= 2:
                    planned_systems = systems[1:]
                    active_navroute_event = e
            continue

        if active_navroute_event is not None and e.event_type == ev.FSD_JUMP:
            expected = planned_systems[leg_index] if leg_index < len(planned_systems) else None
            if e.payload.get("StarSystem") != expected:
                active_navroute_event = None
                planned_systems = []
                continue
            leg_arrivals.append({"system": e.payload.get("StarSystem"), "timestamp": e.timestamp.isoformat()})
            leg_index += 1
            if leg_index == len(planned_systems):
                samples.append(
                    RoutePlotSampleData(
                        navroute_file_name=active_navroute_event.file_name,
                        navroute_line_number=active_navroute_event.line_number,
                        systems=list(planned_systems),
                        completed_at=e.timestamp,
                        leg_arrivals=leg_arrivals,
                    )
                )
                active_navroute_event = None
                planned_systems = []

    return samples


def extract_all_timing_samples(events: Iterable[TimestampedEvent]) -> list[TimingSampleData]:
    events = list(events)
    return (
        extract_jump_samples(events)
        + extract_supercruise_samples(events)
        + extract_dock_samples(events)
        + extract_undock_samples(events)
        + extract_descent_samples(events)
        + extract_ascent_samples(events)
        + extract_mining_cycle_samples(events)
        + extract_bio_sample_samples(events)
    )
