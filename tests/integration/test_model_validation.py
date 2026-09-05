from __future__ import annotations

import dataclasses
import datetime as dt

from app.backtest.model_validation import (
    MAX_MODEL_VALIDATION_TARGETS,
    ModelValidationReport,
    candidate_station_ids,
    discover_commodities_at_station,
    discover_commodities_at_stations,
    run_model_validation,
    select_model_validation_targets,
)
from app.backtest.evaluation_run import EvaluationTarget
from app.db.models.journal import JournalEvent
from app.db.models.market import MarketPredictability
from app.journal import events as ev
from tests.integration.test_eddn_archive import FakeStreamingHttpClient, _archive_url, _compress_day, _envelope

NOW = dt.datetime(2026, 9, 5, 12, 0, tzinfo=dt.timezone.utc)
DISCOVERY_DATE = (NOW - dt.timedelta(days=1)).date()  # 2026-09-04


def _docked_event(session, station_id: int, line_number: int, timestamp: dt.datetime | None = None):
    session.add(
        JournalEvent(
            file_name="Journal.1.log", line_number=line_number, event_type=ev.DOCKED,
            timestamp=timestamp or NOW, payload={"MarketID": station_id, "StationName": f"Station {station_id}"},
        )
    )
    session.commit()


class TestCandidateStationIds:
    def test_returns_distinct_market_ids_from_docked_events_only(self, db_session):
        _docked_event(db_session, 100, 1)
        _docked_event(db_session, 200, 2)
        _docked_event(db_session, 100, 3)  # duplicate station, different dock
        db_session.add(
            JournalEvent(
                file_name="Journal.1.log", line_number=4, event_type=ev.UNDOCKED, timestamp=NOW, payload={},
            )
        )
        db_session.commit()

        assert candidate_station_ids(db_session) == [100, 200]

    def test_empty_when_no_docked_events(self, db_session):
        assert candidate_station_ids(db_session) == []


class TestDiscoverCommoditiesAtStation:
    def test_finds_commodities_reported_for_the_target_station(self):
        envelopes = [
            _envelope(100, f"{DISCOVERY_DATE:%Y-%m-%d}T10:00:00Z", [{"name": "platinum", "sellPrice": 40000, "demand": 5}]),
            _envelope(100, f"{DISCOVERY_DATE:%Y-%m-%d}T14:00:00Z", [{"name": "gold", "sellPrice": 9000, "demand": 3}]),
            _envelope(200, f"{DISCOVERY_DATE:%Y-%m-%d}T11:00:00Z", [{"name": "palladium", "sellPrice": 20000, "demand": 1}]),
        ]
        client = FakeStreamingHttpClient({_archive_url(DISCOVERY_DATE): _compress_day(envelopes)})

        result = discover_commodities_at_station(100, DISCOVERY_DATE, client)

        assert result.station_id == 100
        assert result.discovery_date == DISCOVERY_DATE
        assert result.observation_counts == {"platinum": 1, "gold": 1}  # station 200's palladium excluded

    def test_discovery_empty_when_station_never_reported(self):
        envelopes = [_envelope(200, f"{DISCOVERY_DATE:%Y-%m-%d}T10:00:00Z", [{"name": "gold", "sellPrice": 9000, "demand": 1}])]
        client = FakeStreamingHttpClient({_archive_url(DISCOVERY_DATE): _compress_day(envelopes)})

        result = discover_commodities_at_station(100, DISCOVERY_DATE, client)

        assert result.observation_counts == {}  # DISCOVERY_EMPTY, not an error

    def test_missing_archive_day_is_also_discovery_empty_not_an_error(self):
        client = FakeStreamingHttpClient({})  # 404 for every URL

        result = discover_commodities_at_station(100, DISCOVERY_DATE, client)

        assert result.observation_counts == {}


class TestDiscoverCommoditiesAtStations:
    def test_checks_multiple_stations_in_a_single_archive_scan(self):
        envelopes = [
            _envelope(100, f"{DISCOVERY_DATE:%Y-%m-%d}T10:00:00Z", [{"name": "platinum", "sellPrice": 40000, "demand": 5}]),
            _envelope(200, f"{DISCOVERY_DATE:%Y-%m-%d}T11:00:00Z", [{"name": "gold", "sellPrice": 9000, "demand": 3}]),
            _envelope(300, f"{DISCOVERY_DATE:%Y-%m-%d}T12:00:00Z", [{"name": "silver", "sellPrice": 5000, "demand": 2}]),
        ]
        client = FakeStreamingHttpClient({_archive_url(DISCOVERY_DATE): _compress_day(envelopes)})

        results = discover_commodities_at_stations([100, 200, 300], DISCOVERY_DATE, client)

        assert len(client.requested_urls) == 1  # one archive fetch, not one per station
        assert [r.observation_counts for r in results] == [{"platinum": 1}, {"gold": 1}, {"silver": 1}]

    def test_preserves_input_order_including_discovery_empty_stations(self):
        envelopes = [_envelope(200, f"{DISCOVERY_DATE:%Y-%m-%d}T10:00:00Z", [{"name": "gold", "sellPrice": 9000, "demand": 1}])]
        client = FakeStreamingHttpClient({_archive_url(DISCOVERY_DATE): _compress_day(envelopes)})

        results = discover_commodities_at_stations([100, 200], DISCOVERY_DATE, client)

        assert results[0].station_id == 100
        assert results[0].observation_counts == {}  # DISCOVERY_EMPTY
        assert results[1].station_id == 200
        assert results[1].observation_counts == {"gold": 1}


class TestSelectModelValidationTargets:
    def test_orders_by_observation_count_then_station_then_commodity(self, db_session):
        _docked_event(db_session, 100, 1)
        _docked_event(db_session, 200, 2)
        envelopes = [
            _envelope(100, f"{DISCOVERY_DATE:%Y-%m-%d}T10:00:00Z", [{"name": "platinum", "sellPrice": 40000, "demand": 5}]),
            _envelope(100, f"{DISCOVERY_DATE:%Y-%m-%d}T11:00:00Z", [{"name": "platinum", "sellPrice": 41000, "demand": 5}]),
            _envelope(200, f"{DISCOVERY_DATE:%Y-%m-%d}T10:00:00Z", [{"name": "gold", "sellPrice": 9000, "demand": 1}]),
        ]
        client = FakeStreamingHttpClient({_archive_url(DISCOVERY_DATE): _compress_day(envelopes)})

        targets, discoveries = select_model_validation_targets(db_session, client, NOW)

        assert targets[0].station_id == 100 and targets[0].commodity_name == "platinum"
        assert targets[0].discovery_observation_count == 2
        assert targets[1].station_id == 200 and targets[1].commodity_name == "gold"
        assert {d.station_id for d in discoveries} == {100, 200}

    def test_respects_max_targets(self, db_session):
        for station_id in range(5):
            _docked_event(db_session, station_id, station_id + 1)
        envelopes = [
            _envelope(sid, f"{DISCOVERY_DATE:%Y-%m-%d}T10:00:00Z", [{"name": "platinum", "sellPrice": 40000, "demand": 5}])
            for sid in range(5)
        ]
        client = FakeStreamingHttpClient({_archive_url(DISCOVERY_DATE): _compress_day(envelopes)})

        targets, _ = select_model_validation_targets(db_session, client, NOW, max_targets=2)

        assert len(targets) == 2
        assert MAX_MODEL_VALIDATION_TARGETS == 20

    def test_deterministic_tie_break_when_counts_are_equal(self, db_session):
        _docked_event(db_session, 200, 1)
        _docked_event(db_session, 100, 2)
        envelopes = [
            _envelope(200, f"{DISCOVERY_DATE:%Y-%m-%d}T10:00:00Z", [{"name": "zzz", "sellPrice": 1, "demand": 1}]),
            _envelope(100, f"{DISCOVERY_DATE:%Y-%m-%d}T10:00:00Z", [{"name": "aaa", "sellPrice": 1, "demand": 1}]),
        ]
        client = FakeStreamingHttpClient({_archive_url(DISCOVERY_DATE): _compress_day(envelopes)})

        targets, _ = select_model_validation_targets(db_session, client, NOW)

        # Both have discovery_observation_count == 1 -- tie-break must be
        # (station_id, commodity_name) ascending, not insertion order.
        assert (targets[0].station_id, targets[0].commodity_name) == (100, "aaa")
        assert (targets[1].station_id, targets[1].commodity_name) == (200, "zzz")


class TestRunModelValidation:
    def test_report_has_no_decision_field(self):
        # Structural guarantee (spec §13.3): Model Validation must never
        # be able to produce something that looks like an adoption
        # decision.
        field_names = {f.name for f in dataclasses.fields(ModelValidationReport)}
        assert not any("decision" in name for name in field_names)

    def test_full_run_covers_discovery_and_backtest(self, db_session):
        _docked_event(db_session, 100, 1)
        envelopes_by_date = {}
        for offset in range(3):
            date = (NOW - dt.timedelta(days=offset)).date()
            envelopes_by_date[date] = [
                _envelope(100, f"{date:%Y-%m-%d}T10:00:00Z", [{"name": "platinum", "sellPrice": 40000 + offset * 500, "demand": 5}])
            ]
        payloads = {_archive_url(date): _compress_day(envs) for date, envs in envelopes_by_date.items()}
        client = FakeStreamingHttpClient(payloads)

        report = run_model_validation(
            db_session, client, NOW, window_days_options=(1, 2), t0_interval=dt.timedelta(hours=6)
        )

        assert report.discovery_date == DISCOVERY_DATE
        assert len(report.station_discoveries) == 1
        assert report.station_discoveries[0].station_id == 100
        assert set(report.volatility_by_window.keys()) == {1, 2}
        assert report.freshness is not None
        assert set(report.target_sample_counts.keys()) == {
            EvaluationTarget(t.station_id, t.commodity_name) for t in report.targets
        }

    def test_never_writes_to_market_predictability(self, db_session):
        _docked_event(db_session, 100, 1)
        client = FakeStreamingHttpClient({_archive_url(DISCOVERY_DATE): _compress_day([])})

        run_model_validation(db_session, client, NOW, window_days_options=(1,), t0_interval=dt.timedelta(hours=6))

        assert db_session.query(MarketPredictability).count() == 0
