from __future__ import annotations

import datetime as dt

from app.db.models.journal import JournalEvent
from app.db.models.player import CargoState
from app.mining.state import detect_mining_context, find_historical_ring_locations

NOW = dt.datetime.now(dt.timezone.utc)


def _add_event(session, event_type: str, timestamp: dt.datetime, payload: dict, line: int = 1) -> None:
    session.add(
        JournalEvent(
            file_name="fixture.log",
            line_number=line,
            event_type=event_type,
            timestamp=timestamp,
            payload=payload,
        )
    )


def test_no_cargo_no_activity(db_session):
    context = detect_mining_context(db_session)
    assert context.has_mining_cargo is False
    assert context.ore_cargo == []
    assert context.mining_active is False
    assert context.last_ring_body_id is None


def test_non_ore_cargo_is_excluded(db_session):
    db_session.add(CargoState(commodity_name="tea", quantity=5, updated_at=NOW))
    db_session.commit()

    context = detect_mining_context(db_session)
    assert context.has_mining_cargo is False
    assert context.ore_cargo == []


def test_ore_cargo_without_recent_mining_refined(db_session):
    db_session.add(CargoState(commodity_name="platinum", quantity=10, updated_at=NOW))
    db_session.commit()

    context = detect_mining_context(db_session)
    assert context.has_mining_cargo is True
    assert context.ore_cargo == [("platinum", 10)]
    assert context.mining_active is False
    assert context.generation_confidence < 1.0  # cargo alone, no corroborating activity


def test_recent_mining_refined_with_body_context(db_session):
    _add_event(db_session, "ApproachBody", NOW - dt.timedelta(minutes=10), {"BodyID": 5, "SystemAddress": 123}, line=1)
    _add_event(db_session, "MiningRefined", NOW - dt.timedelta(minutes=5), {"Type": "$platinum_name;"}, line=2)
    db_session.commit()

    context = detect_mining_context(db_session)
    assert context.mining_active is True
    assert context.last_ring_body_id == 5
    assert context.last_ring_system_address == 123
    assert context.generation_confidence == 1.0


def test_recent_mining_refined_without_body_context_lowers_confidence(db_session):
    _add_event(db_session, "MiningRefined", NOW - dt.timedelta(minutes=5), {"Type": "$platinum_name;"}, line=1)
    db_session.commit()

    context = detect_mining_context(db_session)
    assert context.mining_active is True
    assert context.last_ring_body_id is None
    assert context.generation_confidence == 0.75


def test_mining_refined_outside_lookback_window_is_not_active(db_session):
    _add_event(db_session, "MiningRefined", NOW - dt.timedelta(hours=2), {"Type": "$platinum_name;"}, line=1)
    db_session.commit()

    context = detect_mining_context(db_session, lookback=dt.timedelta(minutes=15))
    assert context.mining_active is False


def test_body_context_after_mining_refined_is_not_used(db_session):
    # Only events BEFORE (or at) the MiningRefined timestamp are valid
    # context -- a later ApproachBody could be an entirely different body.
    _add_event(db_session, "MiningRefined", NOW - dt.timedelta(minutes=5), {"Type": "$platinum_name;"}, line=1)
    _add_event(db_session, "ApproachBody", NOW - dt.timedelta(minutes=1), {"BodyID": 99, "SystemAddress": 1}, line=2)
    db_session.commit()

    context = detect_mining_context(db_session)
    assert context.last_ring_body_id is None


class TestFindHistoricalRingLocations:
    def test_no_history_returns_empty(self, db_session):
        assert find_historical_ring_locations(db_session) == []

    def test_ranks_by_frequency(self, db_session):
        line = 1
        # Body A: mined twice
        for _ in range(2):
            _add_event(db_session, "ApproachBody", NOW - dt.timedelta(hours=1), {"BodyID": 1, "SystemAddress": 100}, line)
            line += 1
            _add_event(db_session, "MiningRefined", NOW - dt.timedelta(minutes=50), {"Type": "$platinum_name;"}, line)
            line += 1
        # Body B: mined once
        _add_event(db_session, "ApproachBody", NOW - dt.timedelta(hours=2), {"BodyID": 2, "SystemAddress": 200}, line)
        line += 1
        _add_event(db_session, "MiningRefined", NOW - dt.timedelta(minutes=110), {"Type": "$painite_name;"}, line)
        db_session.commit()

        results = find_historical_ring_locations(db_session)
        assert len(results) == 2
        assert results[0].body_id == 1
        assert results[0].refined_count == 2
        assert results[1].body_id == 2
        assert results[1].refined_count == 1

    def test_events_without_body_context_are_skipped(self, db_session):
        _add_event(db_session, "MiningRefined", NOW - dt.timedelta(minutes=5), {"Type": "$platinum_name;"}, line=1)
        db_session.commit()

        assert find_historical_ring_locations(db_session) == []

    def test_respects_limit(self, db_session):
        line = 1
        for body_id in range(10):
            offset = dt.timedelta(hours=10 - body_id)  # each pair strictly earlier than the last, so they're distinguishable
            _add_event(db_session, "ApproachBody", NOW - offset, {"BodyID": body_id, "SystemAddress": 1}, line)
            line += 1
            _add_event(db_session, "MiningRefined", NOW - offset + dt.timedelta(minutes=1), {"Type": "$platinum_name;"}, line)
            line += 1
        db_session.commit()

        assert len(find_historical_ring_locations(db_session, limit=3)) == 3
