from __future__ import annotations

import bz2
import datetime as dt
import json

from app.collectors.eddn_archive import fetch_commodity_observations, iter_commodity_day


class _FakeResponse:
    def __init__(self, data: bytes, status_code: int = 200):
        self._data = data
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")

    def iter_bytes(self):
        # Split into small chunks to exercise the incremental decompress path,
        # not just a single-shot decompress.
        chunk_size = 37
        for i in range(0, len(self._data), chunk_size):
            yield self._data[i : i + chunk_size]


class _FakeStreamContext:
    def __init__(self, response: _FakeResponse):
        self._response = response

    def __enter__(self) -> _FakeResponse:
        return self._response

    def __exit__(self, *exc_info) -> bool:
        return False


class FakeStreamingHttpClient:
    """Maps exact URLs to pre-built bz2 payloads (or 404 if absent).
    Records every URL requested so tests can assert on request counts."""

    def __init__(self, payloads: dict[str, bytes] | None = None):
        self.payloads = payloads or {}
        self.requested_urls: list[str] = []

    def stream(self, method: str, url: str):
        self.requested_urls.append(url)
        if url not in self.payloads:
            return _FakeStreamContext(_FakeResponse(b"", status_code=404))
        return _FakeStreamContext(_FakeResponse(self.payloads[url]))


def _envelope(market_id: int, timestamp: str, commodities: list[dict]) -> dict:
    return {
        "$schemaRef": "https://eddn.edcd.io/schemas/commodity/3",
        "header": {"uploaderID": "test-uploader"},
        "message": {
            "systemName": "Deciat",
            "stationName": "Farseer Inc",
            "marketId": market_id,
            "timestamp": timestamp,
            "commodities": commodities,
        },
    }


def _compress_day(envelopes: list[dict]) -> bytes:
    lines = b"\n".join(json.dumps(e).encode("utf-8") for e in envelopes)
    return bz2.compress(lines)


def _archive_url(date: dt.date) -> str:
    return f"https://edgalaxydata.space/EDDN/{date:%Y-%m}/Commodity-{date:%Y-%m-%d}.jsonl.bz2"


class TestIterCommodityDay:
    def test_yields_every_envelope_across_chunk_boundaries(self):
        date = dt.date(2026, 8, 20)
        envelopes = [
            _envelope(100, "2026-08-20T10:00:00Z", [{"name": "platinum", "sellPrice": 44586, "demand": 178}]),
            _envelope(200, "2026-08-20T11:00:00Z", [{"name": "gold", "sellPrice": 9000, "demand": 50}]),
        ]
        client = FakeStreamingHttpClient({_archive_url(date): _compress_day(envelopes)})

        result = list(iter_commodity_day(date, client))
        assert len(result) == 2
        assert result[0]["message"]["marketId"] == 100
        assert result[1]["message"]["marketId"] == 200

    def test_missing_day_yields_nothing(self):
        date = dt.date(2026, 8, 21)
        client = FakeStreamingHttpClient({})  # nothing registered -> 404

        assert list(iter_commodity_day(date, client)) == []

    def test_malformed_line_is_skipped_not_fatal(self):
        date = dt.date(2026, 8, 22)
        good = _envelope(100, "2026-08-22T10:00:00Z", [{"name": "platinum", "sellPrice": 1, "demand": 1}])
        payload = bz2.compress(b"not json\n" + json.dumps(good).encode("utf-8"))
        client = FakeStreamingHttpClient({_archive_url(date): payload})

        result = list(iter_commodity_day(date, client))
        assert len(result) == 1
        assert result[0]["message"]["marketId"] == 100


class TestFetchCommodityObservations:
    def test_filters_to_exactly_the_requested_station_and_commodity(self):
        date = dt.date(2026, 8, 20)
        envelopes = [
            _envelope(100, "2026-08-20T10:00:00Z", [
                {"name": "platinum", "sellPrice": 44586, "demand": 178},
                {"name": "gold", "sellPrice": 9000, "demand": 50},  # same station, different commodity
            ]),
            _envelope(200, "2026-08-20T11:00:00Z", [
                {"name": "platinum", "sellPrice": 40000, "demand": 100},  # different station, same commodity
            ]),
        ]
        client = FakeStreamingHttpClient({_archive_url(date): _compress_day(envelopes)})

        result = fetch_commodity_observations(date, station_id=100, commodity_name="platinum", client=client)

        assert len(result) == 1
        assert result[0]["station_id"] == 100
        assert result[0]["commodity_name"] == "platinum"
        assert result[0]["sell_price"] == 44586
        assert result[0]["demand"] == 178
        assert result[0]["source"] == "eddn"

    def test_no_match_returns_empty_list_not_none(self):
        date = dt.date(2026, 8, 20)
        envelopes = [_envelope(999, "2026-08-20T10:00:00Z", [{"name": "gold", "sellPrice": 1, "demand": 1}])]
        client = FakeStreamingHttpClient({_archive_url(date): _compress_day(envelopes)})

        result = fetch_commodity_observations(date, station_id=100, commodity_name="platinum", client=client)
        assert result == []
