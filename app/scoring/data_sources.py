"""DataSource collection — Phase 2-5D.

Spec (docs/PHASE_2_5D_EXPLAINABILITY_DESIGN_BASELINE_V0.1.md §3).

`received_at` stays `None` for market-sourced entries -- `MarketLatest`
has no such column (unlike `MarketSnapshot`), and freshness has only
ever used `observed_at` (docs/PHASE_2_0_DESIGN_BASELINE_V0.1.md §5), so
there's no reason to join MarketSnapshot just to populate a field
nothing reads. `calibration_model` entries carry no timestamp at all
(§3 decision 2) -- a CalibrationModel is a fitted model, not a
timestamped observation.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from app.db.models.player import CargoState
from app.mining.cargo_capacity import get_latest_loadout_event
from app.routing.time import HorizonComponent
from app.scoring.confidence import market_freshness
from app.scoring.models import DataSource


def market_data_sources(market_observed_ats: list[dt.datetime], now: dt.datetime) -> list[DataSource]:
    """One entry per Market observation Value actually used, each with
    its own (pre-aggregation) freshness -- not the candidate-level MIN
    that confidence.py's market_freshness() reports for the whole
    candidate."""
    return [
        DataSource(
            name="market_latest",
            observed_at=observed_at,
            received_at=None,
            freshness=market_freshness([observed_at], now),
        )
        for observed_at in market_observed_ats
    ]


def cargo_state_data_source(session: Session) -> DataSource | None:
    """None if CargoState is empty (nothing held) -- there is nothing
    that was actually "used" to report."""
    rows = session.query(CargoState).all()
    if not rows:
        return None
    latest_update = max(row.updated_at for row in rows)
    return DataSource(name="cargo_state", observed_at=latest_update, received_at=None, freshness=None)


def loadout_data_source(session: Session) -> DataSource | None:
    event = get_latest_loadout_event(session)
    if event is None:
        return None
    return DataSource(name="loadout", observed_at=event.timestamp, received_at=None, freshness=None)


def calibration_data_sources(horizon_components: dict[str, HorizonComponent]) -> list[DataSource]:
    return [
        DataSource(name="calibration_model", observed_at=None, received_at=None, freshness=None)
        for component in horizon_components.values()
        if component.status == "estimated"
    ]
