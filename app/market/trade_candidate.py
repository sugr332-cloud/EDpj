"""Trade Candidate construction — Phase 2-6F-T4-D.

Spec (docs/PHASE_TRADE_T4_EDDN_COMMODITY_INITIAL_AUDIT_V0.1.md §11-14).
Combines a profit-side candidate (origin buy / destination sell, both
already validated against real EDDN commodity/3 data during T4-D) with
inter-system distance/jump count from Spansh's Galaxy Route Plotter
(app.collectors.spansh_route.plot_route).

Field semantics verified directly against EDDN's commodity-v3.0.json
schema: buy_price+supply -> can the player BUY here (origin); sell_price+
demand -> can the player SELL here (destination). Origin/destination
eligibility (commodity KNOWN, origin buy_price>0 AND supply>0,
destination sell_price>0 AND demand>0, destination station structurally
a normal two-way market) is the caller's responsibility -- this module
only assembles the candidate and attaches route data, it does not
re-derive eligibility.

Price plausibility (station_median_ratio, §13) is NOT yet wired in here
-- the production threshold is still unresolved per §14's explicit
decision to defer threshold calibration until after this integration
accumulates real usage data. Callers that want the price-corruption
signal must compute it separately for now.
"""
from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass
from typing import Callable

from app.collectors.spansh_route import RouteHttpClient, plot_route


@dataclass(frozen=True)
class TradeCandidate:
    commodity: str

    origin_station: str
    origin_system: str
    origin_buy_price: int
    origin_supply: int
    origin_observed_at: dt.datetime

    destination_station: str
    destination_system: str
    destination_sell_price: int
    destination_demand: int
    destination_observed_at: dt.datetime

    unit_profit: int

    distance_ly: float | None = None
    jump_count: int | None = None
    profit_per_ly: float | None = None
    profit_per_jump: float | None = None


def attach_route(
    candidate: TradeCandidate,
    ship_range_ly: float,
    client: RouteHttpClient,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> TradeCandidate:
    """Returns a new TradeCandidate with distance/jump fields filled in
    from a real Spansh route query, or unchanged (still None) if the
    route couldn't be computed -- never fabricates a distance or jump
    count. Same-system candidates (distance ~0) still go through
    plot_route rather than being special-cased, since Spansh itself
    correctly returns total_jumps=0 for that case. `sleep_fn` is
    threaded through to plot_route's own polling loop so tests never
    need a real sleep."""
    route = plot_route(candidate.origin_system, candidate.destination_system, ship_range_ly, client, sleep_fn=sleep_fn)
    if route is None:
        return candidate

    distance_ly = route["distance_ly"]
    jump_count = route["total_jumps"]
    profit_per_ly = (candidate.unit_profit / distance_ly) if distance_ly else None
    profit_per_jump = (candidate.unit_profit / jump_count) if jump_count else None

    return TradeCandidate(
        commodity=candidate.commodity,
        origin_station=candidate.origin_station, origin_system=candidate.origin_system,
        origin_buy_price=candidate.origin_buy_price, origin_supply=candidate.origin_supply,
        origin_observed_at=candidate.origin_observed_at,
        destination_station=candidate.destination_station, destination_system=candidate.destination_system,
        destination_sell_price=candidate.destination_sell_price, destination_demand=candidate.destination_demand,
        destination_observed_at=candidate.destination_observed_at,
        unit_profit=candidate.unit_profit,
        distance_ly=distance_ly, jump_count=jump_count,
        profit_per_ly=profit_per_ly, profit_per_jump=profit_per_jump,
    )
