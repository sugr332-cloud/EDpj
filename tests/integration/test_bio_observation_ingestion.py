from __future__ import annotations

import bz2
import datetime as dt
import json

from app.bio.observation_ingestion import ensure_bio_days_fetched, parse_scanorganic_message
from app.db.models.eddn import BioObservation, BioObservationFetchLog


class _FakeResponse:
    def __init__(self, data: bytes, status_code: int = 200):
        self._data = data
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")

    def iter_bytes(self):
        yield self._data


class _FakeStreamContext:
    def __init__(self, response: _FakeResponse):
        self._response = response

    def __enter__(self) -> _FakeResponse:
        return self._response

    def __exit__(self, *exc_info) -> bool:
        return False


class FakeClient:
    def __init__(self, payloads: dict[str, bytes] | None = None):
        self.payloads = payloads or {}
        self.requested_urls: list[str] = []

    def stream(self, method: str, url: str):
        self.requested_urls.append(url)
        if url not in self.payloads:
            return _FakeStreamContext(_FakeResponse(b"", status_code=404))
        return _FakeStreamContext(_FakeResponse(self.payloads[url]))


def _url(date: dt.date) -> str:
    return f"https://edgalaxydata.space/EDDN/{date:%Y-%m}/Journal.ScanOrganic-{date:%Y-%m-%d}.jsonl.bz2"


def _envelope(system_address: int, body_id: int, species: str, timestamp: str, genus: str = "$Codex_Ent_Bacterial_Genus_Name;") -> dict:
    return {
        "$schemaRef": "https://eddn.edcd.io/schemas/scanorganic/1",
        "header": {"uploaderID": "test-uploader"},
        "message": {
            "BodyID": body_id, "SystemAddress": system_address, "StarSystem": "Test System",
            "StarPos": [1.0, 2.0, 3.0], "Genus": genus, "Species": species, "Variant": species + "_variant",
            "ScanType": "Log", "timestamp": timestamp,
        },
    }


def _compress(envelopes: list[dict]) -> bytes:
    return bz2.compress(b"\n".join(json.dumps(e).encode() for e in envelopes))


class TestParseScanorganicMessage:
    def test_parses_all_fields(self):
        msg = _envelope(123, 5, "$Codex_Ent_Bacterial_01_Name;", "2026-08-22T00:03:56Z")["message"]
        row = parse_scanorganic_message(msg)
        assert row["system_address"] == 123
        assert row["body_id"] == 5
        assert row["species"] == "$Codex_Ent_Bacterial_01_Name;"
        assert row["genus"] == "$Codex_Ent_Bacterial_Genus_Name;"
        assert row["star_pos_x"] == 1.0
        assert row["source"] == "scanorganic_archive"


class TestEnsureBioDaysFetched:
    def test_ingests_real_observation(self, db_session):
        date = dt.date(2026, 8, 22)
        envelope = _envelope(123, 5, "$Codex_Ent_Bacterial_01_Name;", "2026-08-22T00:03:56Z")
        client = FakeClient({_url(date): _compress([envelope])})

        ensure_bio_days_fetched(db_session, [date], client)

        rows = db_session.query(BioObservation).all()
        assert len(rows) == 1
        assert rows[0].system_address == 123
        assert rows[0].species == "$Codex_Ent_Bacterial_01_Name;"

    def test_duplicate_system_body_species_collapses_to_one_row(self, db_session):
        date = dt.date(2026, 8, 22)
        envelopes = [
            _envelope(123, 5, "$Codex_Ent_Bacterial_01_Name;", "2026-08-22T00:03:56Z"),
            _envelope(123, 5, "$Codex_Ent_Bacterial_01_Name;", "2026-08-22T05:00:00Z"),
        ]
        client = FakeClient({_url(date): _compress(envelopes)})

        ensure_bio_days_fetched(db_session, [date], client)

        rows = db_session.query(BioObservation).all()
        assert len(rows) == 1

    def test_keeps_earliest_observed_at_across_duplicate_reports(self, db_session):
        date1 = dt.date(2026, 8, 22)
        date2 = dt.date(2026, 8, 23)
        # Later date's archive is processed after the earlier one but
        # (contrived, to prove the ordering guard) reports an EARLIER
        # timestamp for the same fact -- the earliest must win regardless
        # of which archive file it came from.
        client = FakeClient({
            _url(date1): _compress([_envelope(123, 5, "$Codex_Ent_Bacterial_01_Name;", "2026-08-22T12:00:00Z")]),
            _url(date2): _compress([_envelope(123, 5, "$Codex_Ent_Bacterial_01_Name;", "2026-08-22T06:00:00Z")]),
        })

        ensure_bio_days_fetched(db_session, [date1, date2], client)

        row = db_session.query(BioObservation).filter_by(system_address=123, body_id=5).one()
        assert row.observed_at == dt.datetime(2026, 8, 22, 6, 0, 0)

    def test_later_duplicate_report_never_overwrites_with_a_later_timestamp(self, db_session):
        date1 = dt.date(2026, 8, 22)
        date2 = dt.date(2026, 8, 23)
        client = FakeClient({
            _url(date1): _compress([_envelope(123, 5, "$Codex_Ent_Bacterial_01_Name;", "2026-08-22T06:00:00Z")]),
            _url(date2): _compress([_envelope(123, 5, "$Codex_Ent_Bacterial_01_Name;", "2026-08-23T12:00:00Z")]),
        })

        ensure_bio_days_fetched(db_session, [date1, date2], client)

        row = db_session.query(BioObservation).filter_by(system_address=123, body_id=5).one()
        assert row.observed_at == dt.datetime(2026, 8, 22, 6, 0, 0)

    def test_different_species_on_same_body_both_kept(self, db_session):
        date = dt.date(2026, 8, 22)
        envelopes = [
            _envelope(123, 5, "$Codex_Ent_Bacterial_01_Name;", "2026-08-22T00:00:00Z"),
            _envelope(123, 5, "$Codex_Ent_Bacterial_02_Name;", "2026-08-22T00:05:00Z"),
        ]
        client = FakeClient({_url(date): _compress(envelopes)})

        ensure_bio_days_fetched(db_session, [date], client)

        rows = db_session.query(BioObservation).filter_by(system_address=123, body_id=5).all()
        assert len(rows) == 2

    def test_already_fetched_date_is_not_refetched(self, db_session):
        date = dt.date(2026, 8, 22)
        client = FakeClient({_url(date): _compress([])})

        ensure_bio_days_fetched(db_session, [date], client)
        assert len(client.requested_urls) == 1

        ensure_bio_days_fetched(db_session, [date], client)
        assert len(client.requested_urls) == 1  # not requested a second time

    def test_fetch_log_records_the_date(self, db_session):
        date = dt.date(2026, 8, 22)
        client = FakeClient({_url(date): _compress([])})

        ensure_bio_days_fetched(db_session, [date], client)

        logged = db_session.query(BioObservationFetchLog).filter_by(date=date).one_or_none()
        assert logged is not None

    def test_large_batch_beyond_the_chunk_size_all_gets_inserted(self, db_session):
        # Real archive days can hold thousands of messages -- a single
        # INSERT that large would exceed SQLite's bound-variable limit
        # (a real bug hit while running this against the actual archive).
        date = dt.date(2026, 8, 22)
        envelopes = [
            _envelope(123, i, f"$Codex_Ent_Bacterial_{i:02d}_Name;", "2026-08-22T00:00:00Z")
            for i in range(1200)
        ]
        client = FakeClient({_url(date): _compress(envelopes)})

        ensure_bio_days_fetched(db_session, [date], client)

        assert db_session.query(BioObservation).count() == 1200

    def test_malformed_message_does_not_abort_the_whole_day(self, db_session):
        date = dt.date(2026, 8, 22)
        good = _envelope(123, 5, "$Codex_Ent_Bacterial_01_Name;", "2026-08-22T00:00:00Z")
        bad = {"$schemaRef": "x", "header": {}, "message": {"SystemAddress": 999}}  # missing required fields
        client = FakeClient({_url(date): _compress([bad, good])})

        ensure_bio_days_fetched(db_session, [date], client)

        rows = db_session.query(BioObservation).all()
        assert len(rows) == 1
        assert rows[0].system_address == 123
