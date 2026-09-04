"""Journal JSON-Lines parser.

Spec (IMPLEMENTATION_SPEC_V0.2 section 4.1):
  - each line is independent JSON, stored verbatim (parser does not mutate
    the payload)
  - uniqueness key is (file_name, line_number); re-processing the same file
    must not duplicate rows (enforced at the DB layer, see
    app/db/models/journal.py's UniqueConstraint)
  - timestamps are UTC ISO-8601 ("...Z") and are never converted to local
    time before storage/comparison
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Union

from dateutil import parser as date_parser

JOURNAL_GLOB = "Journal.*.log"


@dataclass(frozen=True)
class ParsedLine:
    file_name: str
    line_number: int
    timestamp: datetime
    event_type: str
    payload: dict


@dataclass(frozen=True)
class InvalidLine:
    file_name: str
    line_number: int
    error: str
    raw: str


ParseResult = Union[ParsedLine, InvalidLine]


def parse_journal_timestamp(raw: str) -> datetime:
    """Parse a journal timestamp as UTC. Never converts to local time."""
    ts = date_parser.isoparse(raw)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def iter_journal_files(directory: str | Path) -> Iterator[Path]:
    """Journal filenames encode their start time
    (`Journal.YYYY-MM-DDTHHMMSS.NN.log`), so lexicographic sort is
    chronological."""
    base = Path(directory)
    if not base.is_dir():
        return
    for path in sorted(base.glob(JOURNAL_GLOB)):
        if path.is_file():
            yield path


def parse_journal_line(file_name: str, line_number: int, raw: str) -> ParseResult:
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("journal line is not a JSON object")
        event_type = payload["event"]
        timestamp = parse_journal_timestamp(payload["timestamp"])
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        return InvalidLine(file_name=file_name, line_number=line_number, error=str(exc), raw=raw)
    return ParsedLine(
        file_name=file_name,
        line_number=line_number,
        timestamp=timestamp,
        event_type=event_type,
        payload=payload,
    )


def iter_journal_lines(directory: str | Path) -> Iterator[ParseResult]:
    """Yields ParsedLine for every well-formed line, InvalidLine otherwise.
    Never raises on a bad line — a single corrupt line must not abort the
    whole backfill."""
    for path in iter_journal_files(directory):
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line_number, raw in enumerate(f, start=1):
                raw = raw.strip("\n\r")
                if not raw.strip():
                    continue
                yield parse_journal_line(path.name, line_number, raw)


def iter_journal_lines_from_file(path: str | Path) -> Iterator[ParseResult]:
    """Same as iter_journal_lines but for a single explicit file — used by
    tests and by the live journal watcher (Phase 0-B) which tails one file
    at a time."""
    p = Path(path)
    with p.open("r", encoding="utf-8", errors="replace") as f:
        for line_number, raw in enumerate(f, start=1):
            raw = raw.strip("\n\r")
            if not raw.strip():
                continue
            yield parse_journal_line(p.name, line_number, raw)
