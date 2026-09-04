"""Top-level `edpj` CLI. Phase 0-A registers `journal` and `state`; later
phases add `calibration`, `mining`, `bio`, `score`, `collector`
(SPECIFICATION_V0.4 section 18 / IMPLEMENTATION_SPEC_V0.2 section 3)."""
from __future__ import annotations

import typer

from app.cli.backfill import journal_app
from app.cli.state import state_app

app = typer.Typer(help="edpj — Elite Dangerous state-driven next-action recommender")
app.add_typer(journal_app, name="journal")
app.add_typer(state_app, name="state")


if __name__ == "__main__":
    app()
