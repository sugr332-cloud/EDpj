"""`edpj calibration fit` / `edpj calibration status`

IMPLEMENTATION_SPEC_V0.2.md §3 (required CLI)."""
from __future__ import annotations

import typer

from app.calibration.engine import CALIBRATED_SEGMENT_TYPES, fit_all
from app.db.models.calibration import CalibrationModel
from app.db.session import SessionLocal, init_db

calibration_app = typer.Typer(help="Calibration Engine commands")


@calibration_app.command("fit")
def fit() -> None:
    init_db()
    session = SessionLocal()
    try:
        results = fit_all(session)
    finally:
        session.close()

    for segment_type in CALIBRATED_SEGMENT_TYPES:
        r = results[segment_type]
        seconds = f"{r.seconds:.1f}s" if r.seconds is not None else "N/A"
        typer.echo(
            f"{segment_type}: fit={r.sample_count_fit} eval={r.sample_count_eval} "
            f"status={r.validation_status} seconds={seconds}"
        )


@calibration_app.command("status")
def status() -> None:
    init_db()
    session = SessionLocal()
    try:
        rows = {row.segment_type: row for row in session.query(CalibrationModel).all()}
    finally:
        session.close()

    if not rows:
        typer.echo("no calibration models yet — run `edpj calibration fit` first")
        raise typer.Exit(code=1)

    for segment_type in CALIBRATED_SEGMENT_TYPES:
        row = rows.get(segment_type)
        if row is None:
            typer.echo(f"{segment_type}: not fitted")
            continue
        mae = f"{row.median_absolute_error:.2f}" if row.median_absolute_error is not None else "N/A"
        signed = f"{row.median_signed_error:+.2f}" if row.median_signed_error is not None else "N/A"
        typer.echo(
            f"{segment_type}: fit={row.sample_count_fit} eval={row.sample_count_eval} "
            f"validation={row.validation_status} mae={mae} signed_error={signed} "
            f"fitted_at={row.fitted_at}"
        )
