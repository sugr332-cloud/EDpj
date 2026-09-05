from __future__ import annotations

import datetime as dt

from app.backtest.journal_replay import collect_horizon_diagnostics, reconstruct_player_state_at
from app.db.models.calibration import CalibrationModel
from app.db.models.journal import JournalEvent
from app.db.models.timing import TimingSample
from app.journal import events as ev

T0 = dt.datetime(2026, 8, 20, 12, 0, tzinfo=dt.timezone.utc)


def _event(session, event_type: str, timestamp: dt.datetime, payload: dict, line_number: int):
    session.add(
        JournalEvent(
            file_name="Journal.1.log", line_number=line_number, event_type=event_type,
            timestamp=timestamp, payload=payload,
        )
    )
    session.commit()


def _timing_sample(session, segment_type: str, start_time: dt.datetime, duration_seconds: float, idx: int):
    session.add(
        TimingSample(
            segment_type=segment_type,
            start_file_name="Journal.1.log",
            start_line_number=idx,
            end_file_name="Journal.1.log",
            end_line_number=idx + 1,
            start_time=start_time,
            end_time=start_time + dt.timedelta(seconds=duration_seconds),
            duration_seconds=duration_seconds,
            reached_known_target=True,
        )
    )
    session.commit()


class TestReconstructPlayerStateAt:
    def test_reconstructs_from_events_at_or_before_t0(self, db_session):
        _event(
            db_session, ev.FSD_JUMP, T0 - dt.timedelta(hours=1),
            {"StarSystem": "Deciat", "SystemAddress": 1, "Docked": False}, 1,
        )
        _event(
            db_session, ev.DOCKED, T0,
            {"MarketID": 100, "StationName": "Farseer Inc", "StarSystem": "Deciat", "SystemAddress": 1}, 2,
        )

        state = reconstruct_player_state_at(db_session, T0)

        assert state.fields["current_system"] == "Deciat"
        assert state.fields["docked"] is True
        assert state.fields["current_station_id"] == 100

    def test_ignores_events_after_t0(self, db_session):
        _event(
            db_session, ev.DOCKED, T0 - dt.timedelta(minutes=1),
            {"MarketID": 100, "StationName": "Farseer Inc", "StarSystem": "Deciat", "SystemAddress": 1}, 1,
        )
        _event(db_session, ev.UNDOCKED, T0 + dt.timedelta(minutes=1), {}, 2)

        state = reconstruct_player_state_at(db_session, T0)

        assert state.fields["docked"] is True  # the future UNDOCKED must not apply

    def test_ignores_non_state_relevant_event_types(self, db_session):
        _event(db_session, "Music", T0 - dt.timedelta(minutes=1), {"MusicTrack": "Exploration"}, 1)

        state = reconstruct_player_state_at(db_session, T0)

        assert state.fields == {}

    def test_never_contains_cargo_credits_fuel_fields(self, db_session):
        _event(
            db_session, ev.DOCKED, T0,
            {"MarketID": 100, "StationName": "Farseer Inc", "StarSystem": "Deciat", "SystemAddress": 1}, 1,
        )

        state = reconstruct_player_state_at(db_session, T0)

        forbidden = {"credits", "fuel_main", "cargo_tons", "on_foot"}
        assert forbidden.isdisjoint(state.fields.keys())


class TestFutureLeakagePrevention:
    """Same shape as app/backtest/replay.py's TestFutureLeakagePrevention
    (docs/PHASE_2_6A...§5): record state at T0, then add a large amount
    of contradictory future data, and confirm the recorded state is
    byte-for-byte unchanged."""

    def test_state_unchanged_after_adding_future_events(self, db_session):
        _event(
            db_session, ev.FSD_JUMP, T0 - dt.timedelta(hours=2),
            {"StarSystem": "Deciat", "SystemAddress": 1, "Docked": False}, 1,
        )
        _event(
            db_session, ev.DOCKED, T0 - dt.timedelta(minutes=5),
            {"MarketID": 100, "StationName": "Farseer Inc", "StarSystem": "Deciat", "SystemAddress": 1}, 2,
        )

        before = reconstruct_player_state_at(db_session, T0)

        _event(db_session, ev.UNDOCKED, T0 + dt.timedelta(minutes=1), {}, 3)
        _event(
            db_session, ev.FSD_JUMP, T0 + dt.timedelta(hours=1),
            {"StarSystem": "Sol", "SystemAddress": 999, "Docked": False}, 4,
        )
        for i in range(5, 20):
            _event(
                db_session, ev.DOCKED, T0 + dt.timedelta(hours=i),
                {
                    "MarketID": 999999, "StationName": "Somewhere Else",
                    "StarSystem": "Sol", "SystemAddress": 999,
                },
                i,
            )

        after = reconstruct_player_state_at(db_session, T0)

        assert after == before


class TestCollectHorizonDiagnostics:
    def test_supercruise_always_has_none_relative_error(self, db_session):
        _timing_sample(db_session, "supercruise", T0, 300.0, 1)

        diagnostics = collect_horizon_diagnostics(db_session)

        assert diagnostics[0].relative_error is None
        assert diagnostics[0].estimate.status == "unavailable"

    def test_relative_error_none_when_no_calibration_model_exists(self, db_session):
        _timing_sample(db_session, "jump", T0, 60.0, 1)

        diagnostics = collect_horizon_diagnostics(db_session)

        assert diagnostics[0].relative_error is None
        assert diagnostics[0].estimate.status == "unavailable"

    def test_relative_error_computed_when_estimate_is_available(self, db_session):
        db_session.add(
            CalibrationModel(
                segment_type="jump", seconds=50.0, sample_count_fit=20, sample_count_eval=10,
                median_absolute_error=0.1, median_signed_error=0.0, validation_status="pass",
            )
        )
        db_session.commit()
        _timing_sample(db_session, "jump", T0, 60.0, 1)

        diagnostics = collect_horizon_diagnostics(db_session)

        assert diagnostics[0].estimate.status == "estimated"
        assert diagnostics[0].relative_error == abs(50.0 - 60.0) / 60.0

    def test_does_not_mutate_timing_sample_rows(self, db_session):
        _timing_sample(db_session, "jump", T0, 60.0, 1)

        collect_horizon_diagnostics(db_session)

        row = db_session.query(TimingSample).one()
        assert row.duration_seconds == 60.0
