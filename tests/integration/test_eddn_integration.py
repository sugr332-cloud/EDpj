from __future__ import annotations

import zlib
import json

from app.collectors.eddn import handle_message, handle_raw_message
from app.db.models.eddn import BodyBioSignal, EddnJournalObservation
from app.db.models.market import MarketLatest, MarketSnapshot, StationActivity

COMMODITY_ENVELOPE = {
    "$schemaRef": "https://eddn.edcd.io/schemas/commodity/3",
    "header": {"uploaderID": "cmdr-1", "gatewayTimestamp": "2026-01-01T12:00:05Z"},
    "message": {
        "marketId": 128666762,
        "timestamp": "2026-01-01T12:00:00Z",
        "commodities": [
            {"name": "platinum", "buyPrice": 0, "sellPrice": 44586, "demand": 178, "stock": 0},
        ],
    },
}

JOURNAL_ENVELOPE = {
    "$schemaRef": "https://eddn.edcd.io/schemas/journal/1",
    "header": {"uploaderID": "cmdr-2"},
    "message": {
        "event": "FSSDiscoveryScan",
        "SystemAddress": 123456789,
        "BodyCount": 5,
        "timestamp": "2026-01-01T12:00:00Z",
    },
}

FSSBODYSIGNALS_ENVELOPE = {
    "$schemaRef": "https://eddn.edcd.io/schemas/fssbodysignals/1",
    "header": {"uploaderID": "cmdr-3"},
    "message": {
        "SystemAddress": 123456789,
        "BodyID": 5,
        "timestamp": "2026-01-01T12:00:00Z",
        "Signals": [{"Type": "$SAA_SignalType_Biological;", "Count": 3}],
    },
}


class TestCommodityIngestion:
    def test_writes_market_snapshot_and_market_latest(self, db_session):
        result = handle_message(COMMODITY_ENVELOPE, db_session)
        assert result.schema == "commodity/3"
        assert result.rows_written == 1

        snapshot = db_session.query(MarketSnapshot).filter_by(source="eddn").one()
        assert snapshot.station_id == 128666762
        assert snapshot.commodity_name == "platinum"
        assert snapshot.sell_price == 44586

        latest = db_session.query(MarketLatest).one()
        assert latest.station_id == 128666762
        assert latest.sell_price == 44586

    def test_idempotent_on_duplicate_message(self, db_session):
        handle_message(COMMODITY_ENVELOPE, db_session)
        handle_message(COMMODITY_ENVELOPE, db_session)

        assert db_session.query(MarketSnapshot).count() == 1
        assert db_session.query(MarketLatest).count() == 1

    def test_bumps_station_activity_once_per_message(self, db_session):
        handle_message(COMMODITY_ENVELOPE, db_session)

        activity = db_session.query(StationActivity).one()
        assert activity.station_id == 128666762
        assert activity.observation_count == 1

        second = json.loads(json.dumps(COMMODITY_ENVELOPE))
        second["message"]["timestamp"] = "2026-01-01T13:00:00Z"
        second["message"]["commodities"].append(
            {"name": "gold", "buyPrice": 1, "sellPrice": 2, "demand": 1, "stock": 1}
        )
        handle_message(second, db_session)

        activity = db_session.query(StationActivity).one()
        # One message with two commodities still counts as ONE observation,
        # not two — see _bump_station_activity's docstring.
        assert activity.observation_count == 2
        assert db_session.query(StationActivity).count() == 1

    def test_check1_exact_duplicate_message_does_not_bump_station_activity(self, db_session):
        """Review Check 1: resending the *identical* message (same
        station_id + observed_at) must not double-count observation_count
        — a naive "bump on every message" implementation would inflate it
        on every EDDN redelivery."""
        handle_message(COMMODITY_ENVELOPE, db_session)
        assert db_session.query(StationActivity).one().observation_count == 1

        handle_message(COMMODITY_ENVELOPE, db_session)  # exact resend, byte-for-byte

        assert db_session.query(MarketSnapshot).count() == 1
        assert db_session.query(MarketLatest).count() == 1
        assert db_session.query(StationActivity).one().observation_count == 1  # unchanged

    def test_check2_newer_arrives_before_older_market_latest_keeps_newer(self, db_session):
        """Review Check 2: a newer observation (10:05) arrives first, then
        an older one (10:00) arrives late (e.g. network delay) — the
        older must not overwrite market_latest."""
        newer = json.loads(json.dumps(COMMODITY_ENVELOPE))
        newer["message"]["timestamp"] = "2026-01-01T10:05:00Z"
        newer["message"]["commodities"][0]["sellPrice"] = 500

        older = json.loads(json.dumps(COMMODITY_ENVELOPE))
        older["message"]["timestamp"] = "2026-01-01T10:00:00Z"
        older["message"]["commodities"][0]["sellPrice"] = 100

        handle_message(newer, db_session)
        handle_message(older, db_session)

        latest = db_session.query(MarketLatest).one()
        assert latest.sell_price == 500
        assert latest.observed_at.replace(tzinfo=None).isoformat() == "2026-01-01T10:05:00"

    def test_check3_older_arrives_before_newer_market_latest_advances(self, db_session):
        """Review Check 3: the normal in-order case — an older observation
        (10:00) arrives first, a newer one (10:05) arrives after — the
        newer must replace it."""
        older = json.loads(json.dumps(COMMODITY_ENVELOPE))
        older["message"]["timestamp"] = "2026-01-01T10:00:00Z"
        older["message"]["commodities"][0]["sellPrice"] = 100

        newer = json.loads(json.dumps(COMMODITY_ENVELOPE))
        newer["message"]["timestamp"] = "2026-01-01T10:05:00Z"
        newer["message"]["commodities"][0]["sellPrice"] = 500

        handle_message(older, db_session)
        handle_message(newer, db_session)

        latest = db_session.query(MarketLatest).one()
        assert latest.sell_price == 500
        assert latest.observed_at.replace(tzinfo=None).isoformat() == "2026-01-01T10:05:00"

    def test_market_latest_ordering_uses_payload_timestamp_not_eddn_receipt_time(self, db_session):
        """The "newer wins" comparison must key off the message's own
        `timestamp` field (when the market was actually observed in-game),
        not `received_at` (when *we* processed the EDDN message) — those
        can disagree arbitrarily under network delay/replay."""
        # "received" second (later wall-clock processing) but the payload
        # timestamp is OLDER than what's already stored -> must not win.
        first = json.loads(json.dumps(COMMODITY_ENVELOPE))
        first["message"]["timestamp"] = "2026-01-01T10:05:00Z"
        first["message"]["commodities"][0]["sellPrice"] = 500
        handle_message(first, db_session)

        stale_but_processed_later = json.loads(json.dumps(COMMODITY_ENVELOPE))
        stale_but_processed_later["message"]["timestamp"] = "2026-01-01T10:00:00Z"
        stale_but_processed_later["message"]["commodities"][0]["sellPrice"] = 999
        handle_message(stale_but_processed_later, db_session)  # processed later in wall-clock time

        latest = db_session.query(MarketLatest).one()
        assert latest.sell_price == 500  # the payload-older message did not win despite arriving second

    def test_stale_observation_does_not_overwrite_market_latest(self, db_session):
        handle_message(COMMODITY_ENVELOPE, db_session)

        stale = json.loads(json.dumps(COMMODITY_ENVELOPE))  # deep copy
        stale["message"]["timestamp"] = "2025-01-01T00:00:00Z"  # older than what's stored
        stale["message"]["commodities"][0]["sellPrice"] = 1  # would be visibly wrong if it won

        handle_message(stale, db_session)

        latest = db_session.query(MarketLatest).one()
        assert latest.sell_price == 44586  # unchanged — stale write was rejected


class TestJournalIngestion:
    def test_writes_observation_separate_from_local_journal_events(self, db_session):
        result = handle_message(JOURNAL_ENVELOPE, db_session)
        assert result.schema == "journal/1"
        assert result.rows_written == 1

        obs = db_session.query(EddnJournalObservation).one()
        assert obs.system_address == 123456789
        assert obs.event_type == "FSSDiscoveryScan"
        assert obs.uploader_id == "cmdr-2"

        # This module must never touch journal_events (the LOCAL journal
        # table) or player_state — EDDN journal/1 is a separate concern.
        from app.db.models.journal import JournalEvent
        from app.db.models.player import PlayerState

        assert db_session.query(JournalEvent).count() == 0
        assert db_session.query(PlayerState).count() == 0

    def test_idempotent_on_duplicate_message(self, db_session):
        handle_message(JOURNAL_ENVELOPE, db_session)
        handle_message(JOURNAL_ENVELOPE, db_session)
        assert db_session.query(EddnJournalObservation).count() == 1


class TestFssBodySignalsIngestion:
    def test_writes_bio_signal(self, db_session):
        result = handle_message(FSSBODYSIGNALS_ENVELOPE, db_session)
        assert result.schema == "fssbodysignals/1"
        assert result.rows_written == 1

        row = db_session.query(BodyBioSignal).one()
        assert row.system_address == 123456789
        assert row.body_id == 5
        assert row.count == 3
        assert row.first_observed_at == row.last_observed_at

    def test_idempotent_and_preserves_first_observed_at(self, db_session):
        handle_message(FSSBODYSIGNALS_ENVELOPE, db_session)
        first_row = db_session.query(BodyBioSignal).one()
        original_first_observed = first_row.first_observed_at

        later = json.loads(json.dumps(FSSBODYSIGNALS_ENVELOPE))
        later["message"]["timestamp"] = "2026-02-01T00:00:00Z"
        later["message"]["Signals"][0]["Count"] = 5
        handle_message(later, db_session)

        assert db_session.query(BodyBioSignal).count() == 1  # upserted, not duplicated
        updated_row = db_session.query(BodyBioSignal).one()
        assert updated_row.count == 5  # latest count wins
        assert updated_row.first_observed_at == original_first_observed  # preserved


class TestMalformedAndUnrecognizedMessages:
    def test_unrecognized_schema_is_ignored_not_an_error(self, db_session):
        envelope = {"$schemaRef": "https://eddn.edcd.io/schemas/outfitting/2", "message": {}}
        result = handle_message(envelope, db_session)
        assert result.schema is None
        assert result.rows_written == 0

    def test_malformed_raw_frame_does_not_raise(self, db_session):
        garbage = b"not zlib compressed at all"
        result = handle_raw_message(garbage, db_session)
        assert result.schema is None

    def test_malformed_recognized_schema_does_not_raise_via_handle_raw_message(self, db_session):
        broken = {"$schemaRef": "https://eddn.edcd.io/schemas/commodity/3", "message": {"commodities": []}}
        raw = zlib.compress(json.dumps(broken).encode("utf-8"))
        result = handle_raw_message(raw, db_session)
        assert result.schema is None
        assert db_session.query(MarketSnapshot).count() == 0

    def test_subscriber_loop_survives_a_bad_message_then_processes_a_good_one(self, db_session):
        bad = handle_raw_message(b"garbage", db_session)
        good_raw = zlib.compress(json.dumps(COMMODITY_ENVELOPE).encode("utf-8"))
        good = handle_raw_message(good_raw, db_session)

        assert bad.rows_written == 0
        assert good.rows_written == 1
        assert db_session.query(MarketSnapshot).count() == 1
