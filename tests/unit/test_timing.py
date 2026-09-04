from __future__ import annotations

import datetime as dt

from app.journal.timing import (
    extract_ascent_samples,
    extract_bio_sample_samples,
    extract_descent_samples,
    extract_dock_samples,
    extract_jump_samples,
    extract_mining_cycle_samples,
    extract_route_plot_samples,
    extract_supercruise_samples,
    extract_undock_samples,
)
from app.journal.types import TimestampedEvent

BASE = dt.datetime(2026, 1, 1, 12, 0, 0, tzinfo=dt.timezone.utc)


def E(offset_seconds: float, event_type: str, payload: dict | None = None, line: int = 0, file_name: str = "a.log"):
    return TimestampedEvent(
        file_name=file_name,
        line_number=line,
        timestamp=BASE + dt.timedelta(seconds=offset_seconds),
        event_type=event_type,
        payload=payload or {},
    )


def test_jump_sample_pairs_start_jump_and_fsd_jump():
    events = [
        E(0, "StartJump", {"JumpType": "Hyperspace"}, line=1),
        E(20, "FSDJump", {"StarSystem": "Deciat"}, line=2),
    ]
    samples = extract_jump_samples(events)
    assert len(samples) == 1
    assert samples[0].duration_seconds == 20


def test_jump_sample_ignores_supercruise_charge_up():
    events = [
        E(0, "StartJump", {"JumpType": "Supercruise"}, line=1),
        E(5, "SupercruiseEntry", {}, line=2),
    ]
    assert extract_jump_samples(events) == []


def test_jump_sample_unmatched_start_produces_nothing():
    events = [E(0, "StartJump", {"JumpType": "Hyperspace"}, line=1)]
    assert extract_jump_samples(events) == []


def test_supercruise_reaches_target_via_docked_with_arrival_distance():
    events = [
        E(0, "FSDJump", {"StarSystem": "Deciat"}, line=1),
        E(300, "SupercruiseExit", {}, line=2),
        E(320, "Docked", {"DistFromStarLS": 512.3}, line=3),
    ]
    samples = extract_supercruise_samples(events)
    assert len(samples) == 1
    s = samples[0]
    assert s.duration_seconds == 300
    assert s.reached_known_target is True
    assert s.arrival_dist_from_star_ls == 512.3


def test_supercruise_reaches_target_via_approach_body_without_distance_field():
    events = [
        E(0, "SupercruiseEntry", {}, line=1),
        E(150, "SupercruiseExit", {}, line=2),
        E(160, "ApproachBody", {"Body": "Deciat 2"}, line=3),
    ]
    samples = extract_supercruise_samples(events)
    assert len(samples) == 1
    assert samples[0].reached_known_target is True
    assert samples[0].arrival_dist_from_star_ls is None  # ApproachBody carries no DistFromStarLS -> NO_DATA, not guessed


def test_supercruise_does_not_reach_target_when_next_departure_precedes_a_body():
    events = [
        E(0, "FSDJump", {"StarSystem": "Deciat"}, line=1),
        E(90, "SupercruiseExit", {}, line=2),
        E(95, "FSDJump", {"StarSystem": "Wolf 359"}, line=3),
    ]
    samples = extract_supercruise_samples(events)
    assert len(samples) == 1
    assert samples[0].duration_seconds == 90
    assert samples[0].reached_known_target is False
    assert samples[0].arrival_dist_from_star_ls is None


def test_supercruise_has_no_fixed_120_second_filter():
    """The SupercruiseExit -> Docked gap (here 900s, far past any 120s
    cutoff) must not affect whether a target was reached — the spec explicitly forbids a
    fixed time-window filter for this check. `duration_seconds` measures
    the supercruise leg itself (FSDJump -> SupercruiseExit = 100s); the gap
    afterward belongs to docking, not supercruise."""
    events = [
        E(0, "FSDJump", {}, line=1),
        E(100, "SupercruiseExit", {}, line=2),
        E(100 + 900, "Docked", {"DistFromStarLS": 10.0}, line=3),  # 900s gap
    ]
    samples = extract_supercruise_samples(events)
    assert len(samples) == 1
    assert samples[0].duration_seconds == 100
    assert samples[0].reached_known_target is True


def test_supercruise_multi_jump_route_without_exit_produces_no_sample():
    events = [
        E(0, "FSDJump", {"StarSystem": "A"}, line=1),
        E(25, "FSDJump", {"StarSystem": "B"}, line=2),
        E(50, "FSDJump", {"StarSystem": "C"}, line=3),
    ]
    assert extract_supercruise_samples(events) == []


def test_dock_sample():
    events = [
        E(0, "DockingGranted", {}, line=1),
        E(12, "Docked", {}, line=2),
    ]
    samples = extract_dock_samples(events)
    assert len(samples) == 1
    assert samples[0].duration_seconds == 12


def test_dock_sample_dropped_on_cancellation():
    events = [
        E(0, "DockingGranted", {}, line=1),
        E(5, "DockingCancelled", {}, line=2),
        E(40, "Docked", {}, line=3),
    ]
    assert extract_dock_samples(events) == []


def test_undock_sample():
    events = [
        E(0, "Undocked", {}, line=1),
        E(15, "SupercruiseEntry", {}, line=2),
    ]
    samples = extract_undock_samples(events)
    assert len(samples) == 1
    assert samples[0].duration_seconds == 15


def test_undock_sample_dropped_if_redocked_first():
    events = [
        E(0, "Undocked", {}, line=1),
        E(5, "Docked", {}, line=2),
    ]
    assert extract_undock_samples(events) == []


def test_descent_sample():
    events = [
        E(0, "ApproachBody", {}, line=1),
        E(180, "Touchdown", {}, line=2),
    ]
    samples = extract_descent_samples(events)
    assert len(samples) == 1
    assert samples[0].duration_seconds == 180


def test_descent_sample_dropped_on_aborted_landing():
    events = [
        E(0, "ApproachBody", {}, line=1),
        E(30, "SupercruiseEntry", {}, line=2),  # pulled up, aborted
        E(200, "Touchdown", {}, line=3),
    ]
    assert extract_descent_samples(events) == []


def test_ascent_sample_ends_on_leave_body():
    events = [
        E(0, "Liftoff", {}, line=1),
        E(40, "LeaveBody", {}, line=2),
    ]
    samples = extract_ascent_samples(events)
    assert len(samples) == 1
    assert samples[0].duration_seconds == 40


def test_ascent_sample_ends_on_supercruise_entry():
    events = [
        E(0, "Liftoff", {}, line=1),
        E(35, "SupercruiseEntry", {}, line=2),
    ]
    samples = extract_ascent_samples(events)
    assert len(samples) == 1
    assert samples[0].duration_seconds == 35


def test_mining_cycle_consecutive_samples():
    events = [
        E(0, "MiningRefined", {}, line=1),
        E(120, "MiningRefined", {}, line=2),
        E(245, "MiningRefined", {}, line=3),
    ]
    samples = extract_mining_cycle_samples(events)
    assert [s.duration_seconds for s in samples] == [120, 125]


def test_mining_cycle_interrupted_by_docking():
    events = [
        E(0, "MiningRefined", {}, line=1),
        E(10, "Docked", {}, line=2),
        E(500, "MiningRefined", {}, line=3),
    ]
    assert extract_mining_cycle_samples(events) == []


def test_bio_sample_same_species():
    events = [
        E(0, "ScanOrganic", {"Genus": "Genus1", "Species": "Species1"}, line=1),
        E(90, "ScanOrganic", {"Genus": "Genus1", "Species": "Species1"}, line=2),
    ]
    samples = extract_bio_sample_samples(events)
    assert len(samples) == 1
    assert samples[0].duration_seconds == 90


def test_bio_sample_different_species_not_paired():
    events = [
        E(0, "ScanOrganic", {"Genus": "Genus1", "Species": "Species1"}, line=1),
        E(50, "ScanOrganic", {"Genus": "Genus1", "Species": "Species2"}, line=2),
    ]
    assert extract_bio_sample_samples(events) == []


def test_route_plot_completed_route():
    events = [
        E(0, "NavRoute", {}, line=1),
        E(30, "FSDJump", {"StarSystem": "B"}, line=2),
        E(70, "FSDJump", {"StarSystem": "C"}, line=3),
    ]
    navroute_data = {"Route": [{"StarSystem": "A"}, {"StarSystem": "B"}, {"StarSystem": "C"}]}
    samples = extract_route_plot_samples(events, navroute_data)
    assert len(samples) == 1
    assert samples[0].systems == ["B", "C"]
    assert len(samples[0].leg_arrivals) == 2
    assert samples[0].completed_at == BASE + dt.timedelta(seconds=70)


def test_route_plot_deviation_abandons_sample():
    events = [
        E(0, "NavRoute", {}, line=1),
        E(30, "FSDJump", {"StarSystem": "X"}, line=2),  # not the planned next system
    ]
    navroute_data = {"Route": [{"StarSystem": "A"}, {"StarSystem": "B"}, {"StarSystem": "C"}]}
    assert extract_route_plot_samples(events, navroute_data) == []


def test_route_plot_cleared_before_completion():
    events = [
        E(0, "NavRoute", {}, line=1),
        E(10, "NavRouteClear", {}, line=2),
        E(30, "FSDJump", {"StarSystem": "B"}, line=3),
    ]
    navroute_data = {"Route": [{"StarSystem": "A"}, {"StarSystem": "B"}]}
    assert extract_route_plot_samples(events, navroute_data) == []


def test_route_plot_only_correlates_navroute_data_to_the_last_navroute_event():
    events = [
        E(0, "NavRoute", {}, line=1),  # historical plot — no data available for it
        E(30, "FSDJump", {"StarSystem": "B"}, line=2),  # would match navroute_data's leg, but belongs to old plot
        E(60, "NavRoute", {}, line=3),  # this is the one navroute_data actually describes
        E(90, "FSDJump", {"StarSystem": "B"}, line=4),
    ]
    navroute_data = {"Route": [{"StarSystem": "A"}, {"StarSystem": "B"}]}
    samples = extract_route_plot_samples(events, navroute_data)
    assert len(samples) == 1
    assert samples[0].navroute_line_number == 3


def test_route_plot_no_navroute_data_produces_no_sample():
    events = [
        E(0, "NavRoute", {}, line=1),
        E(30, "FSDJump", {"StarSystem": "B"}, line=2),
    ]
    assert extract_route_plot_samples(events, None) == []
