"""BioObservation ingestion — Phase Bio Species Prediction Backtest.

Spec (docs/BIO_EXTERNAL_DATA_VALIDATION_SPEC_V0.1.md §2.1/§4.2,
docs/PHASE_BIO_SPECIES_PREDICTION_BACKTEST_DESIGN_BASELINE_V0.1.md §2).
Ingests EDDN `scanorganic/1` archive days (via
app.collectors.eddn_archive.iter_scanorganic_day) into `BioObservation`
-- an external, whole-population dataset. This module never reads this
player's own Journal; personal ScanOrganic history is handled entirely
separately (app/bio/conditions.py, app/bio/value.py) and must never be
mixed into this table (spec §2.1's binding separation).
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy.orm import Session

from app.collectors.eddn_archive import StreamingHttpClient, iter_scanorganic_day
from app.db.models.eddn import BioObservation, BioObservationFetchLog
from app.db.upsert import upsert_if_older
from app.journal.parser import parse_journal_timestamp

SCAN_ORGANIC_EVENT = "ScanOrganic"

# A real archive day can hold ~2,000-3,700 scanorganic/1 messages
# (docs/BIO_SCANORGANIC_DATA_AVAILABILITY_INVESTIGATION_V0.1.md §2) --
# one single INSERT with all of them (11 columns each) can exceed
# SQLite's per-statement bound-variable limit. Chunking is a mechanical
# batching detail, not a policy choice -- doesn't affect which rows end
# up upserted, only how many round trips it takes.
_UPSERT_CHUNK_SIZE = 500


class MalformedBioObservation(Exception):
    pass


def parse_scanorganic_message(message: dict[str, Any]) -> dict:
    """scanorganic/1 `message` -> one BioObservation row dict. Required
    fields confirmed present in 100% of real archive messages
    (docs/BIO_SCANORGANIC_DATA_AVAILABILITY_INVESTIGATION_V0.1.md §2) --
    still guards with a clear error rather than a raw KeyError, since a
    malformed line must not abort the whole day's ingestion (caller
    catches and skips, same convention as MalformedEddnMessage)."""
    try:
        return {
            "system_address": message["SystemAddress"],
            "body_id": message["BodyID"],
            "star_system": message["StarSystem"],
            "genus": message["Genus"],
            "species": message["Species"],
            "variant": message.get("Variant"),
            "star_pos_x": message["StarPos"][0],
            "star_pos_y": message["StarPos"][1],
            "star_pos_z": message["StarPos"][2],
            "observed_at": parse_journal_timestamp(message["timestamp"]),
            "source": "scanorganic_archive",
        }
    except (KeyError, IndexError, ValueError) as exc:
        raise MalformedBioObservation(f"scanorganic/1: {exc}") from exc


def ensure_bio_days_fetched(session: Session, dates: list[dt.date], client: StreamingHttpClient) -> None:
    """Ingests each date's Journal.ScanOrganic archive at most once
    (BioObservationFetchLog is date-only keyed -- scanorganic/1 is a
    galaxy-wide population feed, not scoped to specific targets the way
    Market archive fetches are). Rows are upserted with
    upsert_if_older() on (system_address, body_id, species): duplicate
    reports of the same fact keep the EARLIEST observed_at (design doc
    §2.2), never the latest."""
    already_fetched = {row.date for row in session.query(BioObservationFetchLog.date).filter(
        BioObservationFetchLog.date.in_(dates)
    ).all()}
    missing_dates = [d for d in dates if d not in already_fetched]

    for date in missing_dates:
        rows: list[dict] = []
        for envelope in iter_scanorganic_day(date, client):
            message = envelope.get("message")
            if not isinstance(message, dict):
                continue
            try:
                rows.append(parse_scanorganic_message(message))
            except MalformedBioObservation:
                continue

        for i in range(0, len(rows), _UPSERT_CHUNK_SIZE):
            chunk = rows[i : i + _UPSERT_CHUNK_SIZE]
            upsert_if_older(session, BioObservation, chunk, ["system_address", "body_id", "species"], "observed_at")
        session.add(BioObservationFetchLog(date=date, fetched_at=dt.datetime.now(dt.timezone.utc)))
        session.commit()
