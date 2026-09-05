"""State API — Phase 1.

Spec (IMPLEMENTATION_SPEC_V0.2.md §13.1): `GET /api/state`,
`GET /api/state/ship`, `GET /api/state/cargo`. Read-only reflections of
the `player_state`/`cargo_state` singleton Phase 0-A's state reducer
already maintains — this router adds no new state logic.

The fuller state shape SPECIFICATION_V0.4.md §6 documents (has_bio_signals,
unsold_bio_value, mining_context) is not returned here: those fields need
detectors that don't exist yet (Phase 2/3's mining/bio State Detection,
IMPLEMENTATION_SPEC_V0.2.md §8). Returning them as null placeholders would
misrepresent "not implemented yet" as a real observed value, so they're
simply omitted until the phases that compute them land.
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.db.models.player import SINGLETON_ID, CargoState, PlayerState
from app.db.session import SessionLocal

router = APIRouter(prefix="/api/state", tags=["state"])


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


class StateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    current_system: str | None
    current_system_address: int | None
    current_body_id: int | None
    current_body_name: str | None
    current_station_id: int | None
    current_station_name: str | None
    current_ship_id: int | None
    credits: int | None
    fuel_main: float | None
    cargo_tons: int | None
    docked: bool
    landed: bool
    on_foot: bool
    source_status: dict
    updated_at: dt.datetime


class ShipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    current_ship_id: int | None


class CargoItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    commodity_name: str
    quantity: int
    updated_at: dt.datetime


def _get_player_state_or_404(session: Session) -> PlayerState:
    player_state = session.get(PlayerState, SINGLETON_ID)
    if player_state is None:
        raise HTTPException(status_code=404, detail="no state yet — run `edpj journal backfill` first")
    return player_state


@router.get("", response_model=StateResponse)
def get_state(session: Session = Depends(get_session)) -> PlayerState:
    return _get_player_state_or_404(session)


@router.get("/ship", response_model=ShipResponse)
def get_ship(session: Session = Depends(get_session)) -> PlayerState:
    return _get_player_state_or_404(session)


@router.get("/cargo", response_model=list[CargoItem])
def get_cargo(session: Session = Depends(get_session)) -> list[CargoState]:
    return session.query(CargoState).order_by(CargoState.commodity_name).all()
