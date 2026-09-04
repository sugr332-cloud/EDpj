"""Read-only access to Status.json / Cargo.json / Market.json.

Spec (IMPLEMENTATION_SPEC_V0.2 section 4.2): these files must never stop the
process. A missing file is `NO_DATA`; a present-but-unparseable file (the
game can be mid-write) is `STALE` — the caller should keep whatever value it
last had, rather than treat it as an error.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

StateFileStatus = Literal["ok", "no_data", "stale"]


@dataclass(frozen=True)
class StateFileResult:
    status: StateFileStatus
    data: dict | None
    path: Path
    error: str | None = None


def _read_json_file(path: Path) -> StateFileResult:
    if not path.exists():
        return StateFileResult(status="no_data", data=None, path=path)
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return StateFileResult(status="stale", data=None, path=path, error=str(exc))
    return StateFileResult(status="ok", data=data, path=path)


def read_status(journal_dir: str | Path) -> StateFileResult:
    return _read_json_file(Path(journal_dir) / "Status.json")


def read_cargo(journal_dir: str | Path) -> StateFileResult:
    return _read_json_file(Path(journal_dir) / "Cargo.json")


def read_market(journal_dir: str | Path) -> StateFileResult:
    return _read_json_file(Path(journal_dir) / "Market.json")
