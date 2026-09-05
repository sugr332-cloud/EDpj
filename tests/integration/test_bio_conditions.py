from __future__ import annotations

import datetime as dt

from app.bio.conditions import (
    BIOLOGICAL_SIGNAL_TYPE,
    detect_unsold_bio_count,
    find_nearby_bio_signal_bodies,
    has_bio_signals,
)

GEOLOGICAL_SIGNAL_TYPE = "$SAA_SignalType_Geological;"
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


def _add_signal(session, system_address: int, body_id: int, signal_type: str, count: int = 1) -> None:
    session.add(
        BodyBioSignal(
            system_address=system_address, body_id=body_id, signal_type=signal_type, count=count,
            source="eddn", first_observed_at=NOW, last_observed_at=NOW, updated_at=NOW,
        )
    )


class TestHasBioSignals:
    def test_no_signals(self, db_session):
        assert has_bio_signals(db_session, system_address=1, body_id=5) is False

    def test_biological_only(self, db_session):
        _add_signal(db_session, 1, 5, BIOLOGICAL_SIGNAL_TYPE, count=3)
        db_session.commit()
        assert has_bio_signals(db_session, system_address=1, body_id=5) is True

    def test_geological_only(self, db_session):
        # docs/PHASE_3_BIO_VALUE_MODEL_V1...§1: a geological-only body
        # must never be treated as having bio signals.
        _add_signal(db_session, 1, 5, GEOLOGICAL_SIGNAL_TYPE, count=1)
        db_session.commit()
        assert has_bio_signals(db_session, system_address=1, body_id=5) is False

    def test_biological_and_geological_mixed(self, db_session):
        _add_signal(db_session, 1, 5, BIOLOGICAL_SIGNAL_TYPE, count=3)
        _add_signal(db_session, 1, 5, GEOLOGICAL_SIGNAL_TYPE, count=1)
        db_session.commit()
        assert has_bio_signals(db_session, system_address=1, body_id=5) is True

    def test_unknown_signal_type_is_not_treated_as_biological(self, db_session):
        _add_signal(db_session, 1, 5, "$SAA_SignalType_Guardian;", count=1)
        db_session.commit()
        assert has_bio_signals(db_session, system_address=1, body_id=5) is False

    def test_signals_on_a_different_body_do_not_count(self, db_session):
        _add_signal(db_session, 1, 99, BIOLOGICAL_SIGNAL_TYPE, count=3)
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
        _add_signal(db_session, 1, 5, BIOLOGICAL_SIGNAL_TYPE, count=1)
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
        _add_signal(db_session, 2, 5, BIOLOGICAL_SIGNAL_TYPE, count=1)
        db_session.commit()

        results = find_nearby_bio_signal_bodies(db_session, origin, distance_limit_ly=20.0)
        assert results == []

    def test_geological_only_body_is_excluded(self, db_session):
        # docs/PHASE_3_BIO_VALUE_MODEL_V1...§1: same fix applied here.
        origin = _add_system(db_session, 1, "Origin", 0.0, 0.0, 0.0)
        _add_system(db_session, 2, "Nearby", 10.0, 0.0, 0.0)
        _add_signal(db_session, 2, 5, GEOLOGICAL_SIGNAL_TYPE, count=1)
        db_session.commit()

        results = find_nearby_bio_signal_bodies(db_session, origin, distance_limit_ly=20.0)
        assert results == []

    def test_system_with_no_bio_signals_is_excluded(self, db_session):
        origin = _add_system(db_session, 1, "Origin", 0.0, 0.0, 0.0)
        _add_system(db_session, 2, "Empty", 10.0, 0.0, 0.0)
        db_session.commit()

        results = find_nearby_bio_signal_bodies(db_session, origin, distance_limit_ly=20.0)
        assert results == []

    def test_body_with_mixed_signals_is_included_but_only_biological_type_is_reported(self, db_session):
        # A body with both biological and geological signals must still
        # be included (it DOES have real bio signals) -- but
        # signal_types must only ever reflect the biological ones,
        # never the geological row that happens to share the body
        # (docs/PHASE_3_BIO_VALUE_MODEL_V1...§1).
        origin = _add_system(db_session, 1, "Origin", 0.0, 0.0, 0.0)
        _add_system(db_session, 2, "Nearby", 10.0, 0.0, 0.0)
        _add_signal(db_session, 2, 5, BIOLOGICAL_SIGNAL_TYPE, count=3)
        _add_signal(db_session, 2, 5, GEOLOGICAL_SIGNAL_TYPE, count=1)
        db_session.commit()

        results = find_nearby_bio_signal_bodies(db_session, origin, distance_limit_ly=20.0)
        assert len(results) == 1
        assert set(results[0].signal_types) == {BIOLOGICAL_SIGNAL_TYPE}
