from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.cli.backfill import run_backfill
from app.db.models.journal import JournalEvent
from app.db.models.market import MarketSnapshot
from app.db.models.player import SINGLETON_ID, CargoState, PlayerState

JOURNAL_FIXTURES = Path(__file__).parent.parent / "fixtures" / "journal"
STATE_FIXTURES = Path(__file__).parent.parent / "fixtures" / "state_files"


@pytest.fixture()
def journal_dir(tmp_path) -> Path:
    """Elite Dangerous keeps Journal.*.log and Status/Cargo/Market.json in
    the same directory — merge the split fixture dirs into one, like the
    real game layout, so run_backfill can read both."""
    for f in JOURNAL_FIXTURES.glob("Journal.*.log"):
        shutil.copy(f, tmp_path / f.name)
    for name in ("Status.json", "Cargo.json", "Market.json"):
        shutil.copy(STATE_FIXTURES / name, tmp_path / name)
    return tmp_path


def test_backfill_summary_counts(journal_dir, db_session):
    summary = run_backfill(journal_dir, db_session)

    assert summary.files_scanned == 1
    assert summary.lines_scanned == 6
    assert summary.invalid_lines == 1
    assert summary.inserted == 5
    assert summary.skipped_duplicate == 0
    assert summary.first_event.isoformat() == "2026-01-01T12:00:00+00:00"
    assert summary.last_event.isoformat() == "2026-01-01T12:15:00+00:00"


def test_backfill_is_idempotent_on_rerun(journal_dir, db_session):
    run_backfill(journal_dir, db_session)
    second = run_backfill(journal_dir, db_session)

    assert second.inserted == 0
    assert second.skipped_duplicate == 5
    assert db_session.query(JournalEvent).count() == 5


def test_docked_market_capture_inserts_snapshot_rows(journal_dir, db_session):
    run_backfill(journal_dir, db_session)

    rows = db_session.query(MarketSnapshot).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.station_id == 128666762
    assert row.commodity_name == "platinum"
    assert row.source == "journal"
    assert row.sell_price == 44586


def test_docked_market_capture_is_idempotent(journal_dir, db_session):
    run_backfill(journal_dir, db_session)
    run_backfill(journal_dir, db_session)

    assert db_session.query(MarketSnapshot).count() == 1


def test_state_reconstruction(journal_dir, db_session):
    run_backfill(journal_dir, db_session)

    player_state = db_session.get(PlayerState, SINGLETON_ID)
    assert player_state is not None
    assert player_state.current_system == "Deciat"
    assert player_state.current_system_address == 123456789
    assert player_state.current_station_id == 128666762
    assert player_state.current_station_name == "Farseer Inc"
    assert player_state.current_ship_id == 1
    assert player_state.docked is True  # from both Docked event and Status.json Flags
    assert player_state.fuel_main == 8.0
    assert player_state.credits == 950000
    assert player_state.cargo_tons == 5
    assert player_state.source_status == {"status_json": "ok", "cargo_json": "ok"}

    cargo_rows = db_session.query(CargoState).all()
    assert len(cargo_rows) == 1
    assert cargo_rows[0].commodity_name == "platinum"
    assert cargo_rows[0].quantity == 5
