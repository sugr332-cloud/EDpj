"""Top-level `edpj` CLI. Phase 0-A registers `journal` and `state`;
Phase 1 adds `collector` and `api`; Phase 2-1 adds `calibration`; later
phases add `mining`, `bio`, `score`
(SPECIFICATION_V0.4 section 18 / IMPLEMENTATION_SPEC_V0.2 section 3)."""
from __future__ import annotations

import typer

from app.cli.api import api_app
from app.cli.backfill import journal_app
from app.cli.calibration import calibration_app
from app.cli.collector import collector_app
from app.cli.state import state_app

app = typer.Typer(help="edpj — Elite Dangerous state-driven next-action recommender")
app.add_typer(journal_app, name="journal")
app.add_typer(state_app, name="state")
app.add_typer(collector_app, name="collector")
app.add_typer(api_app, name="api")
app.add_typer(calibration_app, name="calibration")


if __name__ == "__main__":
    app()
