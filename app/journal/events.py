"""Journal event-type constants used by Phase 0-A.

Not exhaustive — only the events the Phase 0-A state reducer and market
capture logic actually branch on. Anything else still gets stored verbatim
in `journal_events` by the parser; later phases add handling here as new
timing/candidate features need specific events (see IMPLEMENTATION_SPEC_V0.2
section 5.2 for the segment types Phase 0-B will add: FSDJump,
SupercruiseEntry/Exit, MiningRefined, etc. are already listed below since
Phase 0-A's fixtures exercise them too).
"""
from __future__ import annotations

LOAD_GAME = "LoadGame"
LOADOUT = "Loadout"
LOCATION = "Location"
FSD_JUMP = "FSDJump"
DOCKED = "Docked"
UNDOCKED = "Undocked"
SUPERCRUISE_ENTRY = "SupercruiseEntry"
SUPERCRUISE_EXIT = "SupercruiseExit"
TOUCHDOWN = "Touchdown"
LIFTOFF = "Liftoff"
APPROACH_BODY = "ApproachBody"
LEAVE_BODY = "LeaveBody"
MINING_REFINED = "MiningRefined"
MARKET_SELL = "MarketSell"

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
