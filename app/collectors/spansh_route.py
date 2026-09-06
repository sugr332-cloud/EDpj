"""Spansh Galaxy Route Plotter — on-demand, per-request (Phase 2-6F-T4-D).

Verified live (2026-09-06): `POST /api/route` -> `{"job": id,
"status": "queued"}` (HTTP 202), poll `GET /api/results/{job}` until it
returns HTTP 200 with `state="completed"` -> `result.total_jumps`,
`result.distance` (ly), `result.system_jumps` (per-hop list). Same call
shape as the community `EDMC_SpanshRouter` plugin; `efficiency=60` is
that plugin's own default, not an invented number.

Feasibility already confirmed in the Bio jump-count investigation
(docs/BIO_JUMP_COUNT_FEASIBILITY_INVESTIGATION_V0.1.md): 50/50 real
route computations succeeded across 25 sampled systems x 2 ship ranges.
This module makes that pattern reusable and on-demand -- same policy as
app/collectors/spansh.py: never bulk-precompute routes for every known
candidate, only fetch for the handful of candidates actually being
ranked at decision time.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Protocol

ROUTE_SUBMIT_URL = "https://spansh.co.uk/api/route"
ROUTE_RESULT_URL_TEMPLATE = "https://spansh.co.uk/api/results/{job}"
DEFAULT_EFFICIENCY = 60
POLL_INTERVAL_SECONDS = 1.0
MAX_POLLS = 30
REQUEST_TIMEOUT_SECONDS = 15.0


class RouteHttpClient(Protocol):
    """Satisfied by httpx.Client (needs both post and get) -- tests
    inject a fake instead of hitting the real network."""

    def post(self, url: str, *, params: dict | None = None, timeout: float | None = None) -> Any: ...
    def get(self, url: str, *, timeout: float | None = None) -> Any: ...


def plot_route(
    origin_system: str,
    destination_system: str,
    ship_range_ly: float,
    client: RouteHttpClient,
    efficiency: int = DEFAULT_EFFICIENCY,
    sleep_fn: Callable[[float], None] = time.sleep,
    max_polls: int = MAX_POLLS,
) -> dict | None:
    """Submits a route job and polls until it completes. Returns
    {"total_jumps": int, "distance_ly": float | None} on success, None
    on any failure (unresolvable system name, network error, malformed
    response, or timing out before the job completes) -- never
    fabricates a jump count. `sleep_fn` is injectable so tests don't
    actually sleep."""
    import httpx

    try:
        submit = client.post(
            ROUTE_SUBMIT_URL,
            params={"efficiency": efficiency, "range": ship_range_ly, "from": origin_system, "to": destination_system},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        submit.raise_for_status()
        job = submit.json().get("job")
    except (httpx.HTTPError, ValueError):
        return None
    if not job:
        return None

    result_url = ROUTE_RESULT_URL_TEMPLATE.format(job=job)
    for _ in range(max_polls):
        sleep_fn(POLL_INTERVAL_SECONDS)
        try:
            response = client.get(result_url, timeout=REQUEST_TIMEOUT_SECONDS)
        except httpx.HTTPError:
            return None
        if response.status_code == 200:
            try:
                data = response.json()
            except ValueError:
                return None
            result = data.get("result")
            if not result or "total_jumps" not in result:
                return None
            return {"total_jumps": result["total_jumps"], "distance_ly": result.get("distance")}
        if response.status_code != 202:
            return None
    return None
