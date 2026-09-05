from __future__ import annotations

import datetime as dt

from app.db.models.journal import JournalEvent
from app.mining.cargo_capacity import get_cargo_capacity

NOW = dt.datetime.now(dt.timezone.utc)


def test_returns_none_when_no_loadout_event_recorded(db_session):
    assert get_cargo_capacity(db_session) is None


def test_returns_cargo_capacity_from_latest_loadout_event(db_session):
    db_session.add(
        JournalEvent(
            file_name="f.log", line_number=1, event_type="Loadout",
            timestamp=NOW - dt.timedelta(hours=2), payload={"CargoCapacity": 16},
        )
    )
    db_session.add(
        JournalEvent(
            file_name="f.log", line_number=2, event_type="Loadout",
            timestamp=NOW, payload={"CargoCapacity": 32},
        )
    )
    db_session.commit()

    assert get_cargo_capacity(db_session) == 32


def test_zero_cargo_capacity_is_not_conflated_with_unknown(db_session):
    db_session.add(
        JournalEvent(file_name="f.log", line_number=1, event_type="Loadout", timestamp=NOW, payload={"CargoCapacity": 0})
    )
    db_session.commit()

    assert get_cargo_capacity(db_session) == 0


def test_missing_cargo_capacity_field_returns_none(db_session):
    db_session.add(
        JournalEvent(file_name="f.log", line_number=1, event_type="Loadout", timestamp=NOW, payload={})
    )
    db_session.commit()

    assert get_cargo_capacity(db_session) is None
