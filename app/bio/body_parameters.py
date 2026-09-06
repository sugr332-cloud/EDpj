"""EDSM body physical parameter fetch — on-demand, cached.

Spec (docs/BIO_BODY_PARAMETER_JOIN_INVESTIGATION_V0.1.md): EDSM's
`api-system-v1/bodies?systemName=<name>` returns every known body for a
system, matched to `BioObservation.body_id` via EDSM's own `bodyId`
field. Confirmed against real data: 98.7% of sampled systems have EDSM
body data, 100% of matched bodies had gravity/surfaceTemperature/
atmosphereType/type/subType populated, and zero temporal-leakage cases
(EDSM's own `discovery.date` never fell after the corresponding real
bio observation).
"""
from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.db.models.edsm import BodyPhysicalParameters
from app.db.upsert import upsert_ignore

EDSM_BODIES_URL = "https://www.edsm.net/api-system-v1/bodies"
REQUEST_TIMEOUT_SECONDS = 15.0


class HttpClient(Protocol):
    """Same minimal shape as app/collectors/spansh.py's HttpClient --
    satisfied by httpx.Client, tests inject a fake."""

    def get(self, url: str, *, params: dict | None = None, timeout: float | None = None) -> Any: ...


def fetch_system_bodies(system_name: str, client: HttpClient) -> list[dict] | None:
    """Raw EDSM response `bodies` list for `system_name`, or None on a
    request failure / no data for that system. Never raises."""
    import httpx

    try:
        response = client.get(EDSM_BODIES_URL, params={"systemName": system_name}, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    bodies = data.get("bodies")
    if not bodies:
        return None
    return bodies


def _row_from_edsm_body(system_address: int, body: dict) -> dict | None:
    # `.get(...) is None` (not `"bodyId" not in body`) -- a real EDSM
    # response was found (during the species prediction backtest's real
    # run) to include `"bodyId": null` for at least one body per system,
    # which the key-presence check let through as a fabricated NULL
    # primary-key column value, violating the NOT NULL constraint.
    if body.get("bodyId") is None:
        return None
    return {
        "system_address": system_address,
        "body_id": body["bodyId"],
        "body_type": body.get("type"),
        "sub_type": body.get("subType"),
        "gravity": body.get("gravity"),
        "surface_temperature": body.get("surfaceTemperature"),
        "atmosphere_type": body.get("atmosphereType"),
        "volcanism_type": body.get("volcanismType"),
        "earth_masses": body.get("earthMasses"),
        "radius": body.get("radius"),
        "surface_pressure": body.get("surfacePressure"),
        "atmosphere_composition": body.get("atmosphereComposition"),
        "solid_composition": body.get("solidComposition"),
        "terraforming_state": body.get("terraformingState"),
        "distance_to_arrival": body.get("distanceToArrival"),
        "orbital_period": body.get("orbitalPeriod"),
        "orbital_eccentricity": body.get("orbitalEccentricity"),
        "rotational_period": body.get("rotationalPeriod"),
        "materials": body.get("materials"),
    }


def ensure_body_parameters_cached(
    session: Session, system_address: int, system_name: str, client: HttpClient
) -> None:
    """On a cache miss for `system_address`, fetches every body EDSM
    knows for `system_name` and caches them all at once (one EDSM
    request serves every body in that system, not just the one
    originally needed) -- upsert_ignore since these are static physical
    facts, never expected to change under the same (system, body)."""
    already_cached = (
        session.query(BodyPhysicalParameters.body_id).filter_by(system_address=system_address).first()
    )
    if already_cached is not None:
        return

    bodies = fetch_system_bodies(system_name, client)
    if bodies is None:
        return

    rows = [row for b in bodies if (row := _row_from_edsm_body(system_address, b)) is not None]
    upsert_ignore(session, BodyPhysicalParameters, rows, ["system_address", "body_id"])
    session.commit()


_EXTENDED_FIELDS = [
    "earth_masses", "radius", "surface_pressure", "atmosphere_composition",
    "solid_composition", "terraforming_state", "distance_to_arrival",
    "orbital_period", "orbital_eccentricity", "rotational_period", "materials",
]


def backfill_extended_parameters(session: Session, system_address: int, system_name: str, client: HttpClient) -> int:
    """Re-fetches `system_name` from EDSM and fills in ONLY the extended
    candidate-feature columns (design doc §5.8 -- earthMasses, radius,
    surfacePressure, atmosphereComposition, solidComposition,
    terraformingState, distanceToArrival, orbitalPeriod,
    orbitalEccentricity, rotationalPeriod, materials) on rows already
    cached for `system_address`. Never touches the 5 original core
    columns and never inserts new rows -- this is a backfill for
    systems fetched before these columns existed, not a re-import.
    Returns the number of rows updated (0 if EDSM has no data)."""
    bodies = fetch_system_bodies(system_name, client)
    if bodies is None:
        return 0

    updated = 0
    for b in bodies:
        row = _row_from_edsm_body(system_address, b)
        if row is None:
            continue
        extended_values = {field: row[field] for field in _EXTENDED_FIELDS}
        updated += (
            session.query(BodyPhysicalParameters)
            .filter_by(system_address=system_address, body_id=row["body_id"])
            .update(extended_values)
        )
    session.commit()
    return updated


def get_body_parameters(session: Session, system_address: int, body_id: int) -> BodyPhysicalParameters | None:
    return (
        session.query(BodyPhysicalParameters)
        .filter_by(system_address=system_address, body_id=body_id)
        .one_or_none()
    )
