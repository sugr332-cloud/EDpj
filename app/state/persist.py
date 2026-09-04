"""Writes a ReducedPlayerState into the player_state/cargo_state singleton
rows. Kept separate from reducer.py so the fold logic stays pure and
DB-free (easy to unit test); this module is the thin, integration-tested
seam that talks to SQLAlchemy.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from app.db.models.player import SINGLETON_ID, CargoState, PlayerState
from app.state.reducer import ReducedPlayerState


def apply_reduced_state(session: Session, reduced: ReducedPlayerState) -> PlayerState:
    player_state = session.get(PlayerState, SINGLETON_ID)
    if player_state is None:
        player_state = PlayerState(id=SINGLETON_ID)
        session.add(player_state)

    for key, value in reduced.fields.items():
        if hasattr(player_state, key):
            setattr(player_state, key, value)

    player_state.source_status = reduced.source_status
    player_state.updated_at = dt.datetime.now(dt.timezone.utc)

    # cargo_state is a full-replace snapshot, not an event log.
    session.query(CargoState).delete()
    now = dt.datetime.now(dt.timezone.utc)
    for row in reduced.cargo_rows:
        session.add(CargoState(commodity_name=row["commodity_name"], quantity=row["quantity"], updated_at=now))

    session.flush()
    return player_state
