from __future__ import annotations

import datetime as dt

import pytest

from app.collectors.eddn import (
    MalformedEddnMessage,
    _schema_name,
    parse_commodity_message,
    parse_fssbodysignals_message,
    parse_journal_message,
)

RECEIVED_AT = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)


class TestSchemaName:
    def test_recognizes_commodity(self):
        assert _schema_name("https://eddn.edcd.io/schemas/commodity/3") == "commodity/3"

    def test_recognizes_journal(self):
        assert _schema_name("https://eddn.edcd.io/schemas/journal/1") == "journal/1"

    def test_recognizes_fssbodysignals(self):
        assert _schema_name("https://eddn.edcd.io/schemas/fssbodysignals/1") == "fssbodysignals/1"

    def test_unrecognized_schema_returns_none(self):
        assert _schema_name("https://eddn.edcd.io/schemas/outfitting/2") is None

    def test_trailing_json_pointer_suffix_is_stripped(self):
        assert _schema_name("https://eddn.edcd.io/schemas/commodity/3#/") == "commodity/3"


class TestParseCommodityMessage:
    def test_valid_message_produces_one_row_per_commodity(self):
        message = {
            "systemName": "Deciat",
            "stationName": "Farseer Inc",
            "marketId": 128666762,
            "timestamp": "2026-01-01T12:00:00Z",
            "commodities": [
                {"name": "platinum", "buyPrice": 0, "sellPrice": 44586, "demand": 178, "stock": 0},
                {"name": "gold", "buyPrice": 100, "sellPrice": 120, "demand": 50, "stock": 10},
            ],
        }
        rows = parse_commodity_message(message, RECEIVED_AT)
        assert len(rows) == 2
        assert rows[0]["station_id"] == 128666762
        assert rows[0]["commodity_name"] == "platinum"
        assert rows[0]["sell_price"] == 44586
        assert rows[0]["demand"] == 178
        assert rows[0]["source"] == "eddn"
        assert rows[0]["received_at"] == RECEIVED_AT

    def test_missing_market_id_is_malformed(self):
        message = {"timestamp": "2026-01-01T12:00:00Z", "commodities": []}
        with pytest.raises(MalformedEddnMessage):
            parse_commodity_message(message, RECEIVED_AT)

    def test_missing_timestamp_is_malformed(self):
        message = {"marketId": 1, "commodities": []}
        with pytest.raises(MalformedEddnMessage):
            parse_commodity_message(message, RECEIVED_AT)

    def test_one_bad_commodity_entry_does_not_drop_the_message(self):
        message = {
            "marketId": 1,
            "timestamp": "2026-01-01T12:00:00Z",
            "commodities": [
                {"buyPrice": 0, "sellPrice": 1},  # missing "name" -> skipped
                {"name": "gold", "buyPrice": 100, "sellPrice": 120, "demand": 50, "stock": 10},
            ],
        }
        rows = parse_commodity_message(message, RECEIVED_AT)
        assert len(rows) == 1
        assert rows[0]["commodity_name"] == "gold"


class TestParseJournalMessage:
    def test_valid_message(self):
        message = {
            "event": "FSSDiscoveryScan",
            "StarSystem": "Deciat",
            "SystemAddress": 123456789,
            "BodyCount": 5,
            "timestamp": "2026-01-01T12:00:00Z",
        }
        row = parse_journal_message(message, "uploader-1", RECEIVED_AT)
        assert row["system_address"] == 123456789
        assert row["event_type"] == "FSSDiscoveryScan"
        assert row["uploader_id"] == "uploader-1"
        assert row["body_id"] is None
        assert row["payload"] == message

    def test_missing_uploader_id_defaults_to_empty_string(self):
        message = {"event": "Scan", "SystemAddress": 1, "timestamp": "2026-01-01T12:00:00Z"}
        row = parse_journal_message(message, "", RECEIVED_AT)
        assert row["uploader_id"] == ""

    def test_missing_system_address_is_malformed(self):
        message = {"event": "Scan", "timestamp": "2026-01-01T12:00:00Z"}
        with pytest.raises(MalformedEddnMessage):
            parse_journal_message(message, "u", RECEIVED_AT)


class TestParseFssBodySignalsMessage:
    def test_valid_message(self):
        message = {
            "event": "FSSBodySignals",
            "SystemAddress": 123,
            "BodyID": 5,
            "timestamp": "2026-01-01T12:00:00Z",
            "Signals": [
                {"Type": "$SAA_SignalType_Biological;", "Count": 3},
                {"Type": "$SAA_SignalType_Geological;", "Count": 1},
            ],
        }
        rows = parse_fssbodysignals_message(message, RECEIVED_AT)
        assert len(rows) == 2
        assert rows[0]["system_address"] == 123
        assert rows[0]["body_id"] == 5
        assert rows[0]["signal_type"] == "$SAA_SignalType_Biological;"
        assert rows[0]["count"] == 3
        assert rows[0]["first_observed_at"] == rows[0]["last_observed_at"]

    def test_missing_body_id_is_malformed(self):
        message = {"SystemAddress": 1, "timestamp": "2026-01-01T12:00:00Z", "Signals": []}
        with pytest.raises(MalformedEddnMessage):
            parse_fssbodysignals_message(message, RECEIVED_AT)

    def test_signal_missing_type_is_skipped_not_fatal(self):
        message = {
            "SystemAddress": 1,
            "BodyID": 5,
            "timestamp": "2026-01-01T12:00:00Z",
            "Signals": [{"Count": 3}, {"Type": "$SAA_SignalType_Geological;", "Count": 1}],
        }
        rows = parse_fssbodysignals_message(message, RECEIVED_AT)
        assert len(rows) == 1
        assert rows[0]["signal_type"] == "$SAA_SignalType_Geological;"
