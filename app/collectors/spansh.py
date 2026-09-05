"""Spansh static data — on-demand, cached (Phase 1).

Spec (IMPLEMENTATION_SPEC_V0.2.md §5.3 / §7.1): Phase 1 does not bulk
import the galaxy dump. Systems are resolved and fetched one at a time,
only when actually needed, and cached locally — `get_or_fetch_system`
checks the local `systems` table first and only calls Spansh on a cache
miss (per review feedback: never re-fetch a system already stored).

Endpoints (verified against the live API — docs.spansh.co.uk is a JS
SPA that doesn't expose a fetchable spec, so these were confirmed by
directly querying the API):

  - `GET https://spansh.co.uk/api/systems/field_values/system_names?q=<name>`
    -> `{"min_max": [{"id64", "name", "x", "y", "z"}, ...], "values": [...]}`.
    Fuzzy-matches; callers must filter for an exact `name` match (the API
    itself does not guarantee the first/only result is exact).
  - `GET https://www.spansh.co.uk/api/system/<id64>` -> `{"record": {...}}`,
    a lightweight per-system dump: `bodies` (id64/name/type/subtype/
    distance_to_arrival/landmarks — exploration-summary fields, NOT
    physical parameters) and a top-level `stations` array (market_id/
    name/type/distance_to_arrival/pad counts/services).

IMPORTANT — verified gap: the system-dump endpoint does NOT return
gravity/radius/atmosphere/landable/rings for bodies (confirmed against a
live response), even though IMPLEMENTATION_SPEC_V0.2.md §7.1 lists those
as fields the `bodies` table should hold. Those columns exist in
app/db/models/static.py's Body model but are left NULL (NO_DATA) by this
module — populating them would need Spansh's separate per-body endpoint
(`/api/body/<id64>`), which Phase 1 does not call today since nothing in
this phase consumes those fields yet (mining ring composition is Phase 2,
bio surface conditions are Phase 3). Making N+1 per-body detail calls for
data nothing uses would be needless over-fetching.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.db.models.static import Body, Station, System
from app.db.upsert import upsert_ignore

SYSTEM_NAME_LOOKUP_URL = "https://spansh.co.uk/api/systems/field_values/system_names"
SYSTEM_DUMP_URL_TEMPLATE = "https://www.spansh.co.uk/api/system/{id64}"
REQUEST_TIMEOUT_SECONDS = 10.0


class HttpClient(Protocol):
    """Minimal shape resolve_system_id64/fetch_system need — satisfied by
    httpx.Client, so tests can pass a lightweight fake instead."""

    def get(self, url: str, *, params: dict | None = None, timeout: float | None = None) -> Any: ...


def resolve_system_id64(name: str, client: HttpClient) -> dict | None:
    """Name -> {"id64", "name", "x", "y", "z"} for an exact match, or None
    if not found / the request failed. Never raises — a network error is
    NO_DATA, not a crash."""
    import httpx

    try:
        response = client.get(SYSTEM_NAME_LOOKUP_URL, params={"q": name}, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError):
        return None

    for entry in data.get("min_max", []):
        if entry.get("name") == name:
            return entry
    return None


def fetch_system(id64: int, client: HttpClient) -> dict | None:
    """Fetches the full system dump (`record`) for a known id64, or None
    if not found / the request failed."""
    import httpx

    url = SYSTEM_DUMP_URL_TEMPLATE.format(id64=id64)
    try:
        response = client.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    return data.get("record")


def parse_system_record(record: dict) -> tuple[dict, list[dict], list[dict]]:
    """Pure conversion of a raw Spansh system `record` into
    (system_row, body_rows, station_rows) ready for upsert. Skips any
    body/station entry missing its identifying key rather than guessing
    one."""
    now = dt.datetime.now(dt.timezone.utc)
    system_address = record["id64"]

    system_row = {
        "system_address": system_address,
        "name": record["name"],
        "x": record.get("x", 0.0),
        "y": record.get("y", 0.0),
        "z": record.get("z", 0.0),
        "source": "spansh",
        "updated_at": now,
    }

    body_rows = []
    for b in record.get("bodies", []):
        if "id64" not in b or "name" not in b:
            continue
        body_rows.append(
            {
                "body_id64": b["id64"],
                "system_address": system_address,
                "name": b["name"],
                "body_type": b.get("type"),
                "sub_type": b.get("subtype"),
                "distance_to_arrival_ls": b.get("distance_to_arrival"),
                # Not present in this endpoint — see module docstring.
                "gravity": None,
                "radius": None,
                "atmosphere": None,
                "landable": None,
                "rings": None,
                "source": "spansh",
                "updated_at": now,
            }
        )

    station_rows = []
    for s in record.get("stations", []):
        if "market_id" not in s or "name" not in s:
            continue
        services = s.get("services") or []
        station_type = s.get("type") or ""
        station_rows.append(
            {
                "station_id": s["market_id"],
                "system_address": system_address,
                "name": s["name"],
                "station_type": s.get("type"),
                "distance_to_arrival_ls": s.get("distance_to_arrival"),
                "landing_pad": {
                    "small": s.get("small_pads", 0),
                    "medium": s.get("medium_pads", 0),
                    "large": s.get("large_pads", 0),
                },
                "has_vista_genomics": "Vista Genomics" in services,
                "is_fleet_carrier": "carrier" in station_type.lower(),
                "source": "spansh",
                "updated_at": now,
            }
        )

    return system_row, body_rows, station_rows


def get_or_fetch_system(session: Session, system_name: str, client: HttpClient) -> System | None:
    """Cache-first system lookup: returns the local `System` row if one
    already exists for `system_name`, without any network call. Only on a
    cache miss does it resolve the name via Spansh, fetch the full system
    dump, and upsert systems/bodies/stations locally.

    Returns None if the system can't be resolved/fetched (unknown name,
    network failure) — never fabricates a row."""
    existing = session.query(System).filter(System.name == system_name).one_or_none()
    if existing is not None:
        return existing

    resolved = resolve_system_id64(system_name, client)
    if resolved is None:
        return None
    record = fetch_system(resolved["id64"], client)
    if record is None:
        return None

    system_row, body_rows, station_rows = parse_system_record(record)
    upsert_ignore(session, System, [system_row], ["system_address"])
    if body_rows:
        upsert_ignore(session, Body, body_rows, ["body_id64"])
    if station_rows:
        upsert_ignore(session, Station, station_rows, ["station_id"])
    session.commit()

    return session.get(System, system_row["system_address"])
