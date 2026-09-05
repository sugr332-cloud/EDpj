"""`edpj api serve` — runs the State API (IMPLEMENTATION_SPEC_V0.2.md §13.1)."""
from __future__ import annotations

import typer

api_app = typer.Typer(help="API server")


@api_app.command("serve")
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
) -> None:
    import uvicorn

    from app.db.session import init_db

    init_db()
    uvicorn.run("app.api.app:app", host=host, port=port)
