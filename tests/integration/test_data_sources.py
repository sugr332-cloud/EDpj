from __future__ import annotations

import datetime as dt

from app.db.models.journal import JournalEvent
from app.db.models.player import CargoState
from app.routing.time import TimeEstimate
from app.scoring.data_sources import (
    calibration_data_sources,
    cargo_state_data_source,
    loadout_data_source,
    market_data_sources,
)

NOW = dt.datetime(2026, 8, 20, 12, 0, tzinfo=dt.timezone.utc)


class TestMarketDataSources:
    def test_one_entry_per_observation_with_its_own_freshness(self):
        fresh = NOW - dt.timedelta(minutes=1)
        stale = NOW - dt.timedelta(hours=48)
        sources = market_data_sources([fresh, stale], now=NOW)

        assert len(sources) == 2
        assert all(s.name == "market_latest" for s in sources)
        assert all(s.received_at is None for s in sources)
        by_observed_at = {s.observed_at: s.freshness for s in sources}
        assert by_observed_at[fresh] == 1.0
        assert by_observed_at[stale] == 0.5  # floor, independent of the other (fresh) observation

    def test_empty_input_produces_no_sources(self):
        assert market_data_sources([], now=NOW) == []


class TestCargoStateDataSource:
    def test_none_when_cargo_is_empty(self, db_session):
        assert cargo_state_data_source(db_session) is None

    def test_reports_the_most_recent_update(self, db_session):
        older = NOW - dt.timedelta(hours=2)
        db_session.add(CargoState(commodity_name="platinum", quantity=10, updated_at=older))
        db_session.add(CargoState(commodity_name="painite", quantity=5, updated_at=NOW))
        db_session.commit()

        source = cargo_state_data_source(db_session)
        assert source is not None
        assert source.name == "cargo_state"
        # SQLite doesn't round-trip tzinfo on DateTime(timezone=True) columns
        assert source.observed_at.replace(tzinfo=None) == NOW.replace(tzinfo=None)
        assert source.freshness is None  # not a decaying observation, no freshness model applies


class TestLoadoutDataSource:
    def test_none_when_no_loadout_event_recorded(self, db_session):
        assert loadout_data_source(db_session) is None

    def test_reports_the_latest_loadout_event_timestamp(self, db_session):
        db_session.add(
            JournalEvent(file_name="f.log", line_number=1, event_type="Loadout",
                         timestamp=NOW - dt.timedelta(hours=2), payload={"CargoCapacity": 16})
        )
        db_session.add(
            JournalEvent(file_name="f.log", line_number=2, event_type="Loadout",
                         timestamp=NOW, payload={"CargoCapacity": 32})
        )
        db_session.commit()

        source = loadout_data_source(db_session)
        assert source is not None
        assert source.name == "loadout"
        assert source.observed_at.replace(tzinfo=None) == NOW.replace(tzinfo=None)


class TestCalibrationDataSources:
    def test_one_per_estimated_segment_no_timestamp(self):
        components = {
            "mining_cycle": TimeEstimate(segment_type="mining_cycle", status="estimated", seconds=120.0, confidence=0.85, basis=""),
            "jump": TimeEstimate(segment_type="jump", status="estimated", seconds=30.0, confidence=0.85, basis=""),
        }
        sources = calibration_data_sources(components)
        assert len(sources) == 2
        assert all(s.name == "calibration_model" for s in sources)
        assert all(s.observed_at is None for s in sources)
        assert all(s.freshness is None for s in sources)

    def test_measured_or_unavailable_segments_are_not_included(self):
        components = {
            "mining_cycle": TimeEstimate(segment_type="mining_cycle", status="measured", seconds=120.0, confidence=1.0, basis=""),
            "supercruise": TimeEstimate(segment_type="supercruise", status="unavailable", seconds=None, confidence=None, basis=""),
        }
        assert calibration_data_sources(components) == []
