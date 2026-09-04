"""`edpj journal backfill --dir <journal_dir>`

Spec (IMPLEMENTATION_SPEC_V0.2 section 4.4): scans every journal file in a
directory, inserts new lines (duplicates by (file_name, line_number) are
silently skipped), captures a Market.json snapshot if it matches the most
recent Docked event, and folds everything (plus current Status/Cargo.json)
into the player_state/cargo_state singleton. Prints the summary the spec
requires: files scanned, lines scanned, inserted, skipped duplicate,
invalid lines, first event, last event.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import typer
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.collectors.state_files import read_cargo, read_market, read_status
from app.db.models.journal import JournalEvent
from app.db.models.market import MarketSnapshot
from app.db.session import SessionLocal, init_db
from app.journal import events as ev
from app.journal.extractor import docked_market_matches, extract_market_snapshot
from app.journal.parser import InvalidLine, ParsedLine, iter_journal_lines
from app.state.persist import apply_reduced_state
from app.state.reducer import build_reduced_state

BATCH_SIZE = 1000

journal_app = typer.Typer(help="Journal ingestion commands")


@dataclass
class BackfillSummary:
    files_scanned: int
    lines_scanned: int
    inserted: int
    skipped_duplicate: int
    invalid_lines: int
    first_event: dt.datetime | None
    last_event: dt.datetime | None


def _upsert_ignore(session: Session, model, rows: list[dict], index_elements: list[str]) -> None:
    if not rows:
        return
    dialect = session.get_bind().dialect.name
    if dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as dialect_insert
    elif dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
    else:
        raise NotImplementedError(f"unsupported database dialect for upsert: {dialect}")

    stmt = dialect_insert(model).values(rows)
    stmt = stmt.on_conflict_do_nothing(index_elements=index_elements)
    session.execute(stmt)


def _ingest_journal_lines(directory: Path, session: Session) -> BackfillSummary:
    files_scanned = 0
    lines_scanned = 0
    invalid_lines = 0
    first_event: dt.datetime | None = None
    last_event: dt.datetime | None = None
    seen_files: set[str] = set()

    before_count = session.query(func.count(JournalEvent.id)).scalar() or 0

    batch: list[dict] = []
    for result in iter_journal_lines(directory):
        if result.file_name not in seen_files:
            seen_files.add(result.file_name)
            files_scanned += 1
        lines_scanned += 1

        if isinstance(result, InvalidLine):
            invalid_lines += 1
            continue

        assert isinstance(result, ParsedLine)
        if first_event is None or result.timestamp < first_event:
            first_event = result.timestamp
        if last_event is None or result.timestamp > last_event:
            last_event = result.timestamp

        batch.append(
            {
                "file_name": result.file_name,
                "line_number": result.line_number,
                "event_type": result.event_type,
                "timestamp": result.timestamp,
                "payload": result.payload,
            }
        )
        if len(batch) >= BATCH_SIZE:
            _upsert_ignore(session, JournalEvent, batch, ["file_name", "line_number"])
            batch = []

    if batch:
        _upsert_ignore(session, JournalEvent, batch, ["file_name", "line_number"])

    session.commit()
    after_count = session.query(func.count(JournalEvent.id)).scalar() or 0
    inserted = after_count - before_count
    valid_lines = lines_scanned - invalid_lines
    skipped_duplicate = valid_lines - inserted

    return BackfillSummary(
        files_scanned=files_scanned,
        lines_scanned=lines_scanned,
        inserted=inserted,
        skipped_duplicate=skipped_duplicate,
        invalid_lines=invalid_lines,
        first_event=first_event,
        last_event=last_event,
    )


def _capture_docked_market(directory: Path, session: Session) -> None:
    market_result = read_market(directory)
    if market_result.status != "ok" or market_result.data is None:
        return

    last_docked = (
        session.query(JournalEvent)
        .filter(JournalEvent.event_type == ev.DOCKED)
        .order_by(JournalEvent.timestamp.desc())
        .first()
    )
    if last_docked is None:
        return
    if not docked_market_matches(last_docked.payload, market_result.data):
        return

    batch = extract_market_snapshot(market_result.data, source="journal")
    rows = [
        {
            "station_id": r.station_id,
            "commodity_name": r.commodity_name,
            "buy_price": r.buy_price,
            "sell_price": r.sell_price,
            "supply": r.supply,
            "demand": r.demand,
            "observed_at": r.observed_at,
            "received_at": r.received_at,
            "source": r.source,
            "raw_payload": r.raw_payload,
        }
        for r in batch.rows
    ]
    _upsert_ignore(session, MarketSnapshot, rows, ["station_id", "commodity_name", "observed_at", "source"])
    session.commit()


def _reduce_state(directory: Path, session: Session) -> None:
    status = read_status(directory)
    cargo = read_cargo(directory)
    events = (
        session.query(JournalEvent)
        .filter(JournalEvent.event_type.in_(ev.STATE_RELEVANT_EVENTS))
        .all()
    )
    reduced = build_reduced_state(events, status, cargo)
    apply_reduced_state(session, reduced)
    session.commit()


def run_backfill(directory: Path, session: Session) -> BackfillSummary:
    summary = _ingest_journal_lines(directory, session)
    _capture_docked_market(directory, session)
    _reduce_state(directory, session)
    return summary


@journal_app.command("backfill")
def backfill_command(
    dir: Path = typer.Option(..., "--dir", help="Elite Dangerous journal directory", exists=True, file_okay=False),
) -> None:
    init_db()
    session = SessionLocal()
    try:
        summary = run_backfill(dir, session)
    finally:
        session.close()

    typer.echo(f"files scanned: {summary.files_scanned}")
    typer.echo(f"lines scanned: {summary.lines_scanned}")
    typer.echo(f"inserted: {summary.inserted}")
    typer.echo(f"skipped duplicate: {summary.skipped_duplicate}")
    typer.echo(f"invalid lines: {summary.invalid_lines}")
    typer.echo(f"first event: {summary.first_event.isoformat() if summary.first_event else 'N/A'}")
    typer.echo(f"last event: {summary.last_event.isoformat() if summary.last_event else 'N/A'}")
