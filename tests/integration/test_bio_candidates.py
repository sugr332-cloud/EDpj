from __future__ import annotations

import datetime as dt

from app.bio.candidates import (
    generate_bio_current_body_candidates,
    generate_bio_next_system_candidates,
    generate_bio_return_candidates,
)
from app.bio.conditions import USER_UNSCANNED_UNKNOWN_CONFIDENCE
from app.db.models.eddn import BodyBioSignal
from app.db.models.journal import JournalEvent
from app.db.models.player import SINGLETON_ID, PlayerState
from app.db.models.static import Station, System

NOW = dt.datetime.now(dt.timezone.utc)


def _player_state(**overrides) -> PlayerState:
    defaults = dict(
        id=SINGLETON_ID, current_system="Deciat", current_system_address=1, current_body_id=None,
        current_body_name=None, docked=False, landed=False, on_foot=False, source_status={}, updated_at=NOW,
    )
    defaults.update(overrides)
    return PlayerState(**defaults)


def _add_system(session, system_address: int, name: str, x: float = 0.0, y: float = 0.0, z: float = 0.0) -> None:
    session.add(System(system_address=system_address, name=name, x=x, y=y, z=z, source="spansh", updated_at=NOW))


class TestGenerateBioCurrentBodyCandidates:
    def test_no_current_body_produces_no_candidates(self, db_session):
        player_state = _player_state()
        assert generate_bio_current_body_candidates(db_session, player_state) == []

    def test_body_without_bio_signals_produces_no_candidates(self, db_session):
        player_state = _player_state(current_body_id=5)
        assert generate_bio_current_body_candidates(db_session, player_state) == []

    def test_body_with_bio_signals_produces_candidate_requiring_no_travel(self, db_session):
        db_session.add(
            BodyBioSignal(system_address=1, body_id=5, signal_type="$SAA_SignalType_Biological;", count=3,
                           source="eddn", first_observed_at=NOW, last_observed_at=NOW, updated_at=NOW)
        )
        db_session.commit()
        player_state = _player_state(current_body_id=5, current_body_name="Deciat 2")

        candidates = generate_bio_current_body_candidates(db_session, player_state)

        assert len(candidates) == 1
        assert candidates[0].action == "bio_current_body"
        assert candidates[0].required_segments == ["descent", "bio_sample", "ascent"]
        assert candidates[0].target.body_name == "Deciat 2"
        assert candidates[0].generation_confidence == 1.0


class TestGenerateBioNextSystemCandidates:
    def test_no_current_system_produces_no_candidates(self, db_session):
        player_state = _player_state(current_system_address=None)
        assert generate_bio_next_system_candidates(db_session, player_state) == []

    def test_unresolved_current_system_produces_no_candidates(self, db_session):
        player_state = _player_state()  # current_system_address=1, but no System row exists
        assert generate_bio_next_system_candidates(db_session, player_state) == []

    def test_nearby_system_with_bio_signals_produces_candidate_with_lowered_confidence(self, db_session):
        _add_system(db_session, 1, "Origin", 0.0, 0.0, 0.0)
        _add_system(db_session, 2, "Nearby", 10.0, 0.0, 0.0)
        db_session.add(
            BodyBioSignal(system_address=2, body_id=5, signal_type="bio", count=1, source="eddn",
                           first_observed_at=NOW, last_observed_at=NOW, updated_at=NOW)
        )
        db_session.commit()
        player_state = _player_state()

        candidates = generate_bio_next_system_candidates(db_session, player_state, distance_limit_ly=20.0)

        assert len(candidates) == 1
        assert candidates[0].action == "bio_next_system"
        assert candidates[0].target.system_name == "Nearby"
        assert candidates[0].required_segments == ["jump", "supercruise", "descent", "bio_sample", "ascent"]
        # Never asserted "unscanned=True" -- reflected as reduced confidence instead.
        assert candidates[0].generation_confidence == USER_UNSCANNED_UNKNOWN_CONFIDENCE


class TestGenerateBioReturnCandidates:
    def test_no_unsold_data_produces_no_candidates(self, db_session):
        player_state = _player_state()
        assert generate_bio_return_candidates(db_session, player_state) == []

    def test_unsold_data_with_no_vista_genomics_station_produces_no_candidates(self, db_session):
        _add_system(db_session, 1, "Origin")
        db_session.add(JournalEvent(file_name="f.log", line_number=1, event_type="ScanOrganic",
                                     timestamp=NOW - dt.timedelta(minutes=5), payload={"ScanType": "Analyse"}))
        db_session.commit()
        player_state = _player_state()
        assert generate_bio_return_candidates(db_session, player_state) == []

    def test_unsold_data_with_vista_genomics_station_produces_candidate(self, db_session):
        _add_system(db_session, 1, "Origin", 0.0, 0.0, 0.0)
        _add_system(db_session, 2, "Nearby", 10.0, 0.0, 0.0)
        db_session.add(
            Station(station_id=100, system_address=2, name="Ross Silo", station_type="CraterOutpost",
                    distance_to_arrival_ls=50.0, landing_pad={"small": 1, "medium": 1, "large": 1},
                    has_vista_genomics=True, is_fleet_carrier=False, source="spansh", updated_at=NOW)
        )
        db_session.add(JournalEvent(file_name="f.log", line_number=1, event_type="ScanOrganic",
                                     timestamp=NOW - dt.timedelta(minutes=5), payload={"ScanType": "Analyse"}))
        db_session.commit()
        player_state = _player_state()

        candidates = generate_bio_return_candidates(db_session, player_state)

        assert len(candidates) == 1
        assert candidates[0].action == "bio_return"
        assert candidates[0].target.station_name == "Ross Silo"
        assert candidates[0].target.system_name == "Nearby"
        assert candidates[0].required_segments == ["jump", "supercruise", "dock"]

    def test_picks_the_nearest_vista_genomics_station(self, db_session):
        _add_system(db_session, 1, "Origin", 0.0, 0.0, 0.0)
        _add_system(db_session, 2, "Near", 10.0, 0.0, 0.0)
        _add_system(db_session, 3, "Far", 100.0, 0.0, 0.0)
        db_session.add(Station(station_id=100, system_address=2, name="NearStation", station_type="Outpost",
                                distance_to_arrival_ls=10.0, landing_pad={}, has_vista_genomics=True,
                                is_fleet_carrier=False, source="spansh", updated_at=NOW))
        db_session.add(Station(station_id=200, system_address=3, name="FarStation", station_type="Outpost",
                                distance_to_arrival_ls=10.0, landing_pad={}, has_vista_genomics=True,
                                is_fleet_carrier=False, source="spansh", updated_at=NOW))
        db_session.add(JournalEvent(file_name="f.log", line_number=1, event_type="ScanOrganic",
                                     timestamp=NOW - dt.timedelta(minutes=5), payload={"ScanType": "Analyse"}))
        db_session.commit()
        player_state = _player_state()

        candidates = generate_bio_return_candidates(db_session, player_state)

        assert len(candidates) == 1
        assert candidates[0].target.station_name == "NearStation"
