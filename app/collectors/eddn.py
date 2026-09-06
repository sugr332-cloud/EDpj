"""EDDN subscriber — Phase 1.

Spec (SPECIFICATION_V0.4.md §13 / IMPLEMENTATION_SPEC_V0.2.md §14):
subscribes to three EDDN schemas and persists them idempotently.

  - `commodity/3` (market observations) -> `market_snapshots` (source='eddn')
    + `market_latest`, sharing the exact ingestion shape Phase 0-A already
    uses for journal-sourced Market.json (see app/journal/extractor.py).
    Also bumps `station_activity.observation_count`/`last_observed_at`
    once per message (not per commodity line — one market check is one
    observation of the station, regardless of how many commodities it
    lists).
  - `journal/1` (other commanders' exploration events) ->
    `eddn_journal_observations` — a table structurally separate from the
    player's own `journal_events`; see app/db/models/eddn.py for why. This
    module never touches `player_state`/`cargo_state`.
  - `fssbodysignals/1` (bio/geo signal counts per body) -> `body_bio_signals`,
    upserted (latest known state, `first_observed_at` preserved across
    updates).

Endpoint: `tcp://eddn.edcd.io:9500` (EDDN's live ZeroMQ PUB/SUB relay).
Each message is zlib-compressed JSON; malformed or unrecognized messages
are logged and skipped — one bad message must never stop the subscriber
loop (same principle as Phase 0-A's per-line journal parsing).
"""
from __future__ import annotations

import datetime as dt
import logging
import zlib
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.db.models.eddn import BodyBioSignal, EddnJournalObservation
from app.db.models.market import MarketLatest, MarketSnapshot, StationActivity
from app.db.upsert import dialect_insert_for, upsert_if_newer, upsert_ignore, upsert_preserve_columns
from app.journal.parser import parse_journal_timestamp

logger = logging.getLogger(__name__)

EDDN_ENDPOINT = "tcp://eddn.edcd.io:9500"

SCHEMA_COMMODITY = "commodity/3"
SCHEMA_JOURNAL = "journal/1"
SCHEMA_FSSBODYSIGNALS = "fssbodysignals/1"


class MalformedEddnMessage(ValueError):
    """Raised when a message can't be parsed for a schema we handle.
    Callers catch this per-message and continue the subscriber loop."""


@dataclass(frozen=True)
class DispatchResult:
    schema: str | None  # None if the schema wasn't recognized (still not an error)
    rows_written: int


def _schema_name(schema_ref: str) -> str | None:
    """`$schemaRef` looks like 'https://eddn.edcd.io/schemas/commodity/3'
    (optionally with a '#/...' JSON-pointer suffix, which capture-based
    tools sometimes append) -> 'commodity/3'."""
    ref = schema_ref.split("#", 1)[0].rstrip("/")
    parts = ref.rsplit("/", 2)
    if len(parts) < 2:
        return None
    schema = f"{parts[-2]}/{parts[-1]}"
    if schema in (SCHEMA_COMMODITY, SCHEMA_JOURNAL, SCHEMA_FSSBODYSIGNALS):
        return schema
    return None


def parse_commodity_message(message: dict[str, Any], received_at: dt.datetime | None) -> list[dict]:
    """commodity/3 `message` -> market_snapshots rows (source='eddn').
    `name`/`buyPrice`/`sellPrice`/`stock`/`demand` are already EDDN's
    normalized field names (commodity `name` is the bare internal name,
    e.g. "platinum" — no `$..._name;` wrapping, unlike raw journal
    payloads)."""
    try:
        station_id = message["marketId"]
        observed_at = parse_journal_timestamp(message["timestamp"])
        commodities = message["commodities"]
    except (KeyError, ValueError) as exc:
        raise MalformedEddnMessage(f"commodity/3: {exc}") from exc

    rows = []
    for c in commodities:
        try:
            rows.append(
                {
                    "station_id": station_id,
                    "commodity_name": c["name"],
                    "buy_price": c.get("buyPrice", 0),
                    "sell_price": c.get("sellPrice", 0),
                    "supply": c.get("stock", 0),
                    "demand": c.get("demand", 0),
                    "observed_at": observed_at,
                    "received_at": received_at,
                    "source": "eddn",
                    "raw_payload": c,
                }
            )
        except KeyError:
            continue  # a single malformed commodity entry doesn't drop the whole message
    return rows


def parse_journal_message(message: dict[str, Any], uploader_id: str, received_at: dt.datetime) -> dict:
    """journal/1 `message` -> one eddn_journal_observations row."""
    try:
        system_address = message["SystemAddress"]
        event_type = message["event"]
        observed_at = parse_journal_timestamp(message["timestamp"])
    except (KeyError, ValueError) as exc:
        raise MalformedEddnMessage(f"journal/1: {exc}") from exc

    return {
        "system_address": system_address,
        "body_id": message.get("BodyID"),
        "event_type": event_type,
        "observed_at": observed_at,
        "received_at": received_at,
        "uploader_id": uploader_id or "",
        "payload": message,
    }


def parse_fssbodysignals_message(message: dict[str, Any], received_at: dt.datetime) -> list[dict]:
    """fssbodysignals/1 `message` -> body_bio_signals rows (one per signal
    type reported for the body)."""
    try:
        system_address = message["SystemAddress"]
        body_id = message["BodyID"]
        observed_at = parse_journal_timestamp(message["timestamp"])
        signals = message["signals"] if "signals" in message else message["Signals"]
    except (KeyError, ValueError) as exc:
        raise MalformedEddnMessage(f"fssbodysignals/1: {exc}") from exc

    rows = []
    for sig in signals:
        try:
            signal_type = sig["Type"]
        except KeyError:
            continue
        rows.append(
            {
                "system_address": system_address,
                "body_id": body_id,
                "signal_type": signal_type,
                "count": sig.get("Count", 0),
                "source": "eddn",
                "first_observed_at": observed_at,
                "last_observed_at": observed_at,
                "updated_at": received_at,
            }
        )
    return rows


def _write_commodity_rows(session: Session, rows: list[dict]) -> None:
    if not rows:
        return

    station_id = rows[0]["station_id"]
    observed_at = rows[0]["observed_at"]
    # Same (station_id, observed_at, source) identifies "this market
    # check" regardless of how many commodities it lists — if a row for
    # it already exists, this exact message was already ingested before
    # (a resend), and must not bump station_activity again.
    already_seen = (
        session.query(MarketSnapshot)
        .filter_by(station_id=station_id, observed_at=observed_at, source="eddn")
        .first()
        is not None
    )

    upsert_ignore(session, MarketSnapshot, rows, ["station_id", "commodity_name", "observed_at", "source"])
    latest_rows = [
        {
            "station_id": r["station_id"],
            "commodity_name": r["commodity_name"],
            "buy_price": r["buy_price"],
            "sell_price": r["sell_price"],
            "supply": r["supply"],
            "demand": r["demand"],
            "observed_at": r["observed_at"],
            "source": r["source"],
        }
        for r in rows
    ]
    upsert_if_newer(session, MarketLatest, latest_rows, ["station_id", "commodity_name"], "observed_at")

    if not already_seen:
        _bump_station_activity(session, station_id, observed_at)


def _bump_station_activity(session: Session, station_id: int, observed_at: dt.datetime) -> None:
    """Increments observation_count and overwrites last_observed_at for
    one station. `last_observed_at` is not guarded against an out-of-order
    message moving it backward — unlike market_latest's price data, this
    field is only ever used as an activity/freshness signal, so the rare
    out-of-order case isn't worth a dialect-portable GREATEST()/MAX()
    (Postgres and SQLite spell the 2-argument form differently). Not baked
    into fixed 1h/6h/24h window columns — that aggregation happens at
    query time over market_snapshots."""
    insert = dialect_insert_for(session)
    stmt = insert(StationActivity).values(
        station_id=station_id, observation_count=1, last_observed_at=observed_at
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["station_id"],
        set_={
            "observation_count": StationActivity.observation_count + 1,
            "last_observed_at": stmt.excluded.last_observed_at,
        },
    )
    session.execute(stmt)
    session.expire_all()


def _write_journal_row(session: Session, row: dict) -> None:
    upsert_ignore(session, EddnJournalObservation, [row], ["system_address", "event_type", "observed_at", "uploader_id"])


def _write_bio_signal_rows(session: Session, rows: list[dict]) -> None:
    upsert_preserve_columns(
        session,
        BodyBioSignal,
        rows,
        ["system_address", "body_id", "signal_type"],
        preserve_columns={"first_observed_at"},
    )


def handle_message(envelope: dict[str, Any], session: Session) -> DispatchResult:
    """Dispatches one decoded EDDN envelope ({'$schemaRef', 'header',
    'message'}) to the matching schema handler and persists it. Returns
    DispatchResult(schema=None, rows_written=0) for an envelope whose
    schema isn't one we subscribe to (not an error — just ignored) and
    raises MalformedEddnMessage for a recognized schema with an
    unparseable body, so the caller can log-and-continue per message."""
    schema_ref = envelope.get("$schemaRef", "")
    schema = _schema_name(schema_ref)
    if schema is None:
        return DispatchResult(schema=None, rows_written=0)

    message = envelope.get("message")
    if not isinstance(message, dict):
        raise MalformedEddnMessage(f"{schema}: missing or invalid 'message'")

    received_at = dt.datetime.now(dt.timezone.utc)
    header = envelope.get("header") or {}
    uploader_id = header.get("uploaderID", "")

    if schema == SCHEMA_COMMODITY:
        rows = parse_commodity_message(message, received_at)
        _write_commodity_rows(session, rows)
        session.commit()
        return DispatchResult(schema=schema, rows_written=len(rows))

    if schema == SCHEMA_JOURNAL:
        row = parse_journal_message(message, uploader_id, received_at)
        _write_journal_row(session, row)
        session.commit()
        return DispatchResult(schema=schema, rows_written=1)

    if schema == SCHEMA_FSSBODYSIGNALS:
        rows = parse_fssbodysignals_message(message, received_at)
        _write_bio_signal_rows(session, rows)
        session.commit()
        return DispatchResult(schema=schema, rows_written=len(rows))

    return DispatchResult(schema=None, rows_written=0)  # unreachable given _schema_name's allowlist


def handle_raw_message(raw: bytes, session: Session) -> DispatchResult:
    """Decompresses+decodes one raw ZMQ frame and dispatches it. Never
    raises on a malformed frame — logs and returns a no-op result, so the
    live subscriber loop below never dies on one bad message."""
    import json

    try:
        envelope = json.loads(zlib.decompress(raw))
    except (zlib.error, UnicodeDecodeError, ValueError) as exc:
        logger.warning("dropping unparseable EDDN frame: %s", exc)
        return DispatchResult(schema=None, rows_written=0)

    try:
        return handle_message(envelope, session)
    except MalformedEddnMessage as exc:
        logger.warning("dropping malformed EDDN message: %s", exc)
        session.rollback()
        return DispatchResult(schema=None, rows_written=0)


def subscribe(session_factory, endpoint: str = EDDN_ENDPOINT, timeout_ms: int = 600_000) -> None:  # pragma: no cover
    """Live subscriber loop — connects to EDDN and processes messages
    forever. Not exercised by the automated test suite (would require a
    live network double); `handle_message`/`handle_raw_message` above
    carry the actual logic and are what's tested."""
    import zmq

    context = zmq.Context()
    subscriber = context.socket(zmq.SUB)
    subscriber.setsockopt(zmq.SUBSCRIBE, b"")
    subscriber.setsockopt(zmq.RCVTIMEO, timeout_ms)
    subscriber.connect(endpoint)

    try:
        while True:
            try:
                raw = subscriber.recv()
            except zmq.Again:
                continue
            session = session_factory()
            try:
                handle_raw_message(raw, session)
            finally:
                session.close()
    finally:
        subscriber.close()
        context.term()
