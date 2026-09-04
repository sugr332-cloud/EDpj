from __future__ import annotations

import datetime as dt
from pathlib import Path

from app.journal.parser import (
    InvalidLine,
    ParsedLine,
    iter_journal_files,
    iter_journal_lines,
    parse_journal_line,
    parse_journal_timestamp,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "journal"


def test_utc_parsing_never_converts_to_local():
    ts = parse_journal_timestamp("2026-01-01T12:00:00Z")
    assert ts.tzinfo is not None
    assert ts.utcoffset() == dt.timedelta(0)
    assert ts.hour == 12  # not shifted to any local timezone


def test_parse_journal_timestamp_without_explicit_z_is_treated_as_utc():
    ts = parse_journal_timestamp("2026-01-01T12:00:00")
    assert ts.utcoffset() == dt.timedelta(0)


def test_iter_journal_files_is_chronological():
    files = list(iter_journal_files(FIXTURES))
    assert [f.name for f in files] == sorted(f.name for f in files)


def test_valid_line_parses_to_parsed_line():
    result = parse_journal_line("Journal.test.log", 1, '{"timestamp":"2026-01-01T12:00:00Z","event":"LoadGame","ShipID":1}')
    assert isinstance(result, ParsedLine)
    assert result.event_type == "LoadGame"
    assert result.payload["ShipID"] == 1
    assert result.line_number == 1
    assert result.file_name == "Journal.test.log"


def test_invalid_json_line_is_invalid_line_not_an_exception():
    result = parse_journal_line("Journal.test.log", 2, "not json at all")
    assert isinstance(result, InvalidLine)
    assert result.line_number == 2


def test_line_missing_event_field_is_invalid():
    result = parse_journal_line("Journal.test.log", 3, '{"timestamp":"2026-01-01T12:00:00Z"}')
    assert isinstance(result, InvalidLine)


def test_iter_journal_lines_counts_valid_and_invalid():
    results = list(iter_journal_lines(FIXTURES))
    valid = [r for r in results if isinstance(r, ParsedLine)]
    invalid = [r for r in results if isinstance(r, InvalidLine)]
    assert len(valid) == 5  # LoadGame, Loadout, FSDJump, SupercruiseExit, Docked
    assert len(invalid) == 1  # "this line is not valid json at all"


def test_reprocessing_the_same_file_yields_identical_keys():
    """(file_name, line_number) must be stable across repeated parses —
    the DB-level uniqueness dedup depends on it."""
    first = [(r.file_name, r.line_number) for r in iter_journal_lines(FIXTURES) if isinstance(r, ParsedLine)]
    second = [(r.file_name, r.line_number) for r in iter_journal_lines(FIXTURES) if isinstance(r, ParsedLine)]
    assert first == second
