"""Shared event shape used by both the Phase 0-A state reducer and the
Phase 0-B timing extractor, so neither cares whether it's folding freshly
parsed lines or rows already persisted to `journal_events`.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


@dataclass
class TimestampedEvent:
    file_name: str
    line_number: int
    timestamp: dt.datetime
    event_type: str
    payload: dict
