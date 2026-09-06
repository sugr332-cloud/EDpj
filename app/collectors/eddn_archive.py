"""Historical EDDN archive fetch — Phase 2-5A.

Spec (docs/PHASE_2_5A_MARKET_PREDICTABILITY_IMPLEMENTATION_BASELINE_V0.1.md
§1/§4): verified real archive at https://edgalaxydata.space/EDDN/, one
`Commodity-YYYY-MM-DD.jsonl.bz2` per day (~60-112MB compressed), holding
raw EDDN commodity/3 envelopes going back to 2017-08 — no per-station/
commodity server-side filtering exists, so every query costs a full
day's download regardless of target. This module streams+decompresses
one day at a time and reuses `app.collectors.eddn.parse_commodity_message`
for the row shape rather than re-implementing the commodity/3 schema —
the archive's per-line envelope is the same `{"$schemaRef","header",
"message"}` shape the live EDDN subscriber already parses, just replayed
from a file instead of a ZeroMQ socket.
"""
from __future__ import annotations

import bz2
import datetime as dt
import json
from typing import Any, Iterator, Protocol

from app.collectors.eddn import MalformedEddnMessage, parse_commodity_message

ARCHIVE_BASE_URL = "https://edgalaxydata.space/EDDN"


class StreamResponse(Protocol):
    status_code: int

    def raise_for_status(self) -> None: ...
    def iter_bytes(self) -> Iterator[bytes]: ...


class StreamContextManager(Protocol):
    def __enter__(self) -> StreamResponse: ...
    def __exit__(self, *exc_info: object) -> None: ...


class StreamingHttpClient(Protocol):
    """Same shape as app/collectors/spansh.py's HttpClient Protocol --
    tests inject a fake instead of hitting the real network."""

    def stream(self, method: str, url: str) -> StreamContextManager: ...


def _archive_url(date: dt.date) -> str:
    return f"{ARCHIVE_BASE_URL}/{date:%Y-%m}/Commodity-{date:%Y-%m-%d}.jsonl.bz2"


def _scanorganic_archive_url(date: dt.date) -> str:
    return f"{ARCHIVE_BASE_URL}/{date:%Y-%m}/Journal.ScanOrganic-{date:%Y-%m-%d}.jsonl.bz2"


def _iter_archive_day(url: str, client: StreamingHttpClient) -> Iterator[dict[str, Any]]:
    """Streams one day's archive file at `url`, yielding each parsed EDDN
    envelope ({"$schemaRef","header","message"}). Never buffers the whole
    (decompressed) file in memory -- decompresses and splits into lines
    incrementally as bytes arrive. A day that doesn't exist in the
    archive yet (e.g. today, or a date before the archive's own start)
    yields nothing rather than raising -- that's "no data available",
    not an error. Shared by iter_commodity_day() and
    iter_scanorganic_day() -- only the URL differs between schemas
    (Phase Bio Species Prediction Backtest design doc §2.3)."""
    with client.stream("GET", url) as response:
        if response.status_code == 404:
            return
        response.raise_for_status()

        decompressor = bz2.BZ2Decompressor()
        buffer = b""
        for chunk in response.iter_bytes():
            buffer += decompressor.decompress(chunk)
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except ValueError:
                    continue  # one malformed archive line must not abort the whole day
        remainder = buffer.strip()
        if remainder:
            try:
                yield json.loads(remainder)
            except ValueError:
                pass


def iter_commodity_day(date: dt.date, client: StreamingHttpClient) -> Iterator[dict[str, Any]]:
    return _iter_archive_day(_archive_url(date), client)


def iter_scanorganic_day(date: dt.date, client: StreamingHttpClient) -> Iterator[dict[str, Any]]:
    """Journal.ScanOrganic-YYYY-MM-DD.jsonl.bz2 -- confirmed present on the
    same real archive (docs/BIO_SCANORGANIC_DATA_AVAILABILITY_
    INVESTIGATION_V0.1.md §1), a whole-population feed with no per-target
    filtering (every commander's real ScanOrganic reports for that day)."""
    return _iter_archive_day(_scanorganic_archive_url(date), client)


def fetch_commodity_observations(
    date: dt.date, station_id: int, commodity_name: str, client: StreamingHttpClient
) -> list[dict[str, Any]]:
    """One day's worth of rows for exactly (station_id, commodity_name),
    reusing app.collectors.eddn.parse_commodity_message so the commodity/3
    field mapping (marketId/commodities[].name/buyPrice/...) is defined
    in exactly one place in this codebase. Non-matching rows are dropped
    immediately, never accumulated."""
    matches: list[dict[str, Any]] = []
    for envelope in iter_commodity_day(date, client):
        message = envelope.get("message")
        if not isinstance(message, dict) or message.get("marketId") != station_id:
            continue
        try:
            rows = parse_commodity_message(message, received_at=dt.datetime.now(dt.timezone.utc))
        except MalformedEddnMessage:
            continue  # malformed envelope -- same "skip and continue" policy as the live subscriber
        matches.extend(row for row in rows if row["commodity_name"] == commodity_name)
    return matches
