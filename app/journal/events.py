"""Journal event-type constants used by Phase 0-A and Phase 0-B.

Not exhaustive — only the events the state reducer, market capture, and
timing extractor actually branch on. Anything else still gets stored
verbatim in `journal_events` by the parser; later phases add handling here
as new timing/candidate features need specific events.
"""
from __future__ import annotations

LOAD_GAME = "LoadGame"
LOADOUT = "Loadout"
LOCATION = "Location"
FSD_JUMP = "FSDJump"
START_JUMP = "StartJump"
DOCKED = "Docked"
UNDOCKED = "Undocked"
DOCKING_GRANTED = "DockingGranted"
DOCKING_CANCELLED = "DockingCancelled"
DOCKING_TIMEOUT = "DockingTimeout"
DOCKING_DENIED = "DockingDenied"
SUPERCRUISE_ENTRY = "SupercruiseEntry"
SUPERCRUISE_EXIT = "SupercruiseExit"
TOUCHDOWN = "Touchdown"
LIFTOFF = "Liftoff"
APPROACH_BODY = "ApproachBody"
LEAVE_BODY = "LeaveBody"
MINING_REFINED = "MiningRefined"
MARKET_SELL = "MarketSell"
SCAN_ORGANIC = "ScanOrganic"
NAV_ROUTE = "NavRoute"
NAV_ROUTE_CLEAR = "NavRouteClear"

# Events the Phase 0-A state reducer folds into player_state.
STATE_RELEVANT_EVENTS = frozenset(
    {
        LOAD_GAME,
        LOADOUT,
        LOCATION,
        FSD_JUMP,
        DOCKED,
        UNDOCKED,
        SUPERCRUISE_ENTRY,
        SUPERCRUISE_EXIT,
        TOUCHDOWN,
        LIFTOFF,
        APPROACH_BODY,
        LEAVE_BODY,
    }
)

# Events the Phase 0-B timing extractor scans for (IMPLEMENTATION_SPEC_V0.2
# section 5.2: jump, supercruise, dock, undock, descent, ascent, bio_sample,
# mining_cycle, route_plot segment types).
TIMING_RELEVANT_EVENTS = frozenset(
    {
        START_JUMP,
        FSD_JUMP,
        DOCKING_GRANTED,
        DOCKING_CANCELLED,
        DOCKING_TIMEOUT,
        DOCKING_DENIED,
        DOCKED,
        UNDOCKED,
        SUPERCRUISE_ENTRY,
        SUPERCRUISE_EXIT,
        TOUCHDOWN,
        LIFTOFF,
        APPROACH_BODY,
        LEAVE_BODY,
        MINING_REFINED,
        SCAN_ORGANIC,
        NAV_ROUTE,
        NAV_ROUTE_CLEAR,
    }
)
