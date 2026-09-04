"""`edpj state show` — prints the current player_state/cargo_state
singleton. Not required by the Phase 0-A exit criteria, but the state
reducer has nothing else to inspect it with until the API (Phase 1+)
exists, and the spec's CLI-first principle (SPECIFICATION_V0.4 section 18)
says CLI verification should exist before the API layer does.
"""
from __future__ import annotations

import typer

from app.db.models.player import SINGLETON_ID, CargoState, PlayerState
from app.db.session import SessionLocal, init_db

state_app = typer.Typer(help="Player state commands")


@state_app.command("show")
def show_state() -> None:
    init_db()
    session = SessionLocal()
    try:
        player_state = session.get(PlayerState, SINGLETON_ID)
        if player_state is None:
            typer.echo("no state yet — run `edpj journal backfill --dir <journal_dir>` first")
            raise typer.Exit(code=1)

        typer.echo(f"system: {player_state.current_system} ({player_state.current_system_address})")
        typer.echo(f"body: {player_state.current_body_name} ({player_state.current_body_id})")
        typer.echo(f"station: {player_state.current_station_name} ({player_state.current_station_id})")
        typer.echo(f"ship_id: {player_state.current_ship_id}")
        typer.echo(f"docked: {player_state.docked}  landed: {player_state.landed}  on_foot: {player_state.on_foot}")
        typer.echo(f"credits: {player_state.credits}  fuel_main: {player_state.fuel_main}")
        typer.echo(f"cargo_tons: {player_state.cargo_tons}")
        typer.echo(f"source_status: {player_state.source_status}")
        typer.echo(f"updated_at: {player_state.updated_at}")

        cargo_rows = session.query(CargoState).order_by(CargoState.commodity_name).all()
        if cargo_rows:
            typer.echo("cargo:")
            for row in cargo_rows:
                typer.echo(f"  {row.commodity_name}: {row.quantity}")
    finally:
        session.close()
