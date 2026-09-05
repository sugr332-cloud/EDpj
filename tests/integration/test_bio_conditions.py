from __future__ import annotations

import datetime as dt

from app.bio.conditions import (
    detect_unsold_bio_count,
    find_nearby_bio_signal_bodies,
    has_bio_signals,
)
from app.db.models.eddn import BodyBioSignal
from app.db.models.journal import JournalEvent
from app.db.models.static import System

NOW = dt.datetime.now(dt.timezone.utc)


def _add_journal_event(session, event_type: str, timestamp: dt.datetime, payload: dict, line: int) -> None:
    session.add(
        JournalEvent(file_name="fixture.log", line_number=line, event_type=event_type, timestamp=timestamp, payload=payload)
    )


def _add_system(session, system_address: int, name: str, x: float, y: float, z: float) -> System:
    system = System(system_address=system_address, name=name, x=x, y=y, z=z, source="spansh", updated_at=NOW)
    session.add(system)
    return system


class TestHasBioSignals:
    def test_no_signals(self, db_session):
        assert has_bio_signals(db_session, system_address=1, body_id=5) is False

    def test_has_signals(self, db_session):
        db_session.add(
            BodyBioSignal(
                system_address=1, body_id=5, signal_type="$SAA_SignalType_Biological;", count=3,
                source="eddn", first_observed_at=NOW, last_observed_at=NOW, updated_at=NOW,
            )
        )
        db_session.commit()
        assert has_bio_signals(db_session, system_address=1, body_id=5) is True

    def test_signals_on_a_different_body_do_not_count(self, db_session):
        db_session.add(
            BodyBioSignal(
                system_address=1, body_id=99, signal_type="$SAA_SignalType_Biological;", count=3,
                source="eddn", first_observed_at=NOW, last_observed_at=NOW, updated_at=NOW,
            )
        )
        db_session.commit()
        assert has_bio_signals(db_session, system_address=1, body_id=5) is False


class TestDetectUnsoldBioCount:
    def test_no_scans_no_sales(self, db_session):
        assert detect_unsold_bio_count(db_session) == 0

    def test_completed_scans_with_no_prior_sale_all_count(self, db_session):
        _add_journal_event(db_session, "ScanOrganic", NOW - dt.timedelta(minutes=10), {"ScanType": "Log"}, 1)
        _add_journal_event(db_session, "ScanOrganic", NOW - dt.timedelta(minutes=5), {"ScanType": "Analyse"}, 2)
        _add_journal_event(db_session, "ScanOrganic", NOW - dt.timedelta(minutes=4), {"ScanType": "Analyse"}, 3)
        db_session.commit()

        # Only "Analyse" (species-completing) scans count -- "Log" does not.
        assert detect_unsold_bio_count(db_session) == 2

    def test_scans_before_last_sale_are_not_counted(self, db_session):
        _add_journal_event(db_session, "ScanOrganic", NOW - dt.timedelta(minutes=20), {"ScanType": "Analyse"}, 1)
        _add_journal_event(db_session, "SellOrganicData", NOW - dt.timedelta(minutes=10), {}, 2)
        _add_journal_event(db_session, "ScanOrganic", NOW - dt.timedelta(minutes=5), {"ScanType": "Analyse"}, 3)
        db_session.commit()

        assert detect_unsold_bio_count(db_session) == 1  # only the post-sale scan


class TestFindNearbyBioSignalBodies:
    def test_excludes_origin_system(self, db_session):
        origin = _add_system(db_session, 1, "Origin", 0.0, 0.0, 0.0)
        db_session.add(
            BodyBioSignal(system_address=1, body_id=5, signal_type="bio", count=1, source="eddn",
                           first_observed_at=NOW, last_observed_at=NOW, updated_at=NOW)
        )
        db_session.commit()

        results = find_nearby_bio_signal_bodies(db_session, origin, distance_limit_ly=100.0)
        assert results == []

    def test_within_distance_limit_with_signals_is_included(self, db_session):
        origin = _add_system(db_session, 1, "Origin", 0.0, 0.0, 0.0)
        _add_system(db_session, 2, "Nearby", 10.0, 0.0, 0.0)  # distance = 10
        db_session.add(
            BodyBioSignal(system_address=2, body_id=5, signal_type="$SAA_SignalType_Biological;", count=3,
                           source="eddn", first_observed_at=NOW, last_observed_at=NOW, updated_at=NOW)
        )
        db_session.commit()

        results = find_nearby_bio_signal_bodies(db_session, origin, distance_limit_ly=20.0)
        assert len(results) == 1
        assert results[0].system.name == "Nearby"
        assert results[0].body_id == 5
        assert results[0].distance_ly == 10.0

    def test_beyond_distance_limit_is_excluded(self, db_session):
        origin = _add_system(db_session, 1, "Origin", 0.0, 0.0, 0.0)
        _add_system(db_session, 2, "Far", 100.0, 0.0, 0.0)  # distance = 100
        db_session.add(
            BodyBioSignal(system_address=2, body_id=5, signal_type="bio", count=1, source="eddn",
                           first_observed_at=NOW, last_observed_at=NOW, updated_at=NOW)
        )
        db_session.commit()

        results = find_nearby_bio_signal_bodies(db_session, origin, distance_limit_ly=20.0)
        assert results == []

    def test_system_with_no_bio_signals_is_excluded(self, db_session):
        origin = _add_system(db_session, 1, "Origin", 0.0, 0.0, 0.0)
        _add_system(db_session, 2, "Empty", 10.0, 0.0, 0.0)
        db_session.commit()

        results = find_nearby_bio_signal_bodies(db_session, origin, distance_limit_ly=20.0)
        assert results == []

    def test_multiple_signal_types_on_same_body_are_grouped(self, db_session):
        origin = _add_system(db_session, 1, "Origin", 0.0, 0.0, 0.0)
        _add_system(db_session, 2, "Nearby", 10.0, 0.0, 0.0)
        db_session.add_all(
            [
                BodyBioSignal(system_address=2, body_id=5, signal_type="$SAA_SignalType_Biological;", count=3,
                               source="eddn", first_observed_at=NOW, last_observed_at=NOW, updated_at=NOW),
                BodyBioSignal(system_address=2, body_id=5, signal_type="$SAA_SignalType_Geological;", count=1,
                               source="eddn", first_observed_at=NOW, last_observed_at=NOW, updated_at=NOW),
            ]
        )
        db_session.commit()

        results = find_nearby_bio_signal_bodies(db_session, origin, distance_limit_ly=20.0)
        assert len(results) == 1  # one row per body, not per signal_type
        assert set(results[0].signal_types) == {"$SAA_SignalType_Biological;", "$SAA_SignalType_Geological;"}
