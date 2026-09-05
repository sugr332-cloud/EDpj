"""`edpj collector eddn` / `edpj collector spansh --system <name>`

IMPLEMENTATION_SPEC_V0.2.md §3: Phase 1+ CLI. `collector journal`/
`collector state` (live-watching the local journal/state files) are not
implemented here — Phase 1 only adds the EDDN and Spansh collectors.
"""
from __future__ import annotations

import typer

from app.db.session import SessionLocal, init_db

collector_app = typer.Typer(help="Phase 1 collectors (EDDN, Spansh)")


@collector_app.command("eddn")
def collector_eddn() -> None:
    """Runs the live EDDN subscriber loop (blocks forever)."""
    from app.collectors.eddn import subscribe

    init_db()
    typer.echo("connecting to EDDN...")
    subscribe(SessionLocal)


@collector_app.command("spansh")
def collector_spansh(
    system: str = typer.Option(..., "--system", help="Star system name to resolve and cache"),
) -> None:
    """One-shot on-demand fetch of a system's static data from Spansh,
    cached locally (no re-fetch on a cache hit)."""
    import httpx

    from app.collectors.spansh import get_or_fetch_system

    init_db()
    session = SessionLocal()
    try:
        with httpx.Client() as client:
            result = get_or_fetch_system(session, system, client)
    finally:
        session.close()

    if result is None:
        typer.echo(f"could not resolve or fetch system: {system}")
        raise typer.Exit(code=1)

    typer.echo(f"system_address={result.system_address} name={result.name} source={result.source}")
