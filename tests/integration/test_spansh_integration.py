from __future__ import annotations

from dataclasses import dataclass, field

from app.collectors.spansh import get_or_fetch_system
from app.db.models.static import Body, Station, System

SOL_LOOKUP_RESPONSE = {"min_max": [{"id64": 10477373803, "name": "Sol", "x": 0.0, "y": 0.0, "z": 0.0}]}

SOL_SYSTEM_RESPONSE = {
    "record": {
        "id64": 10477373803,
        "name": "Sol",
        "x": 0.0,
        "y": 0.0,
        "z": 0.0,
        "bodies": [
            {
                "id64": 36028807496337771,
                "name": "Mercury",
                "type": "Planet",
                "subtype": "Metal-rich body",
                "distance_to_arrival": 173.944857,
            }
        ],
        "stations": [
            {
                "market_id": 128016384,
                "name": "Daedalus",
                "type": "Orbis Starport",
                "distance_to_arrival": 173.999,
                "small_pads": 10,
                "medium_pads": 13,
                "large_pads": 6,
                "services": ["Dock", "Market", "Vista Genomics"],
            }
        ],
    }
}


@dataclass
class FakeResponse:
    _json: dict

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._json


@dataclass
class FakeHttpClient:
    """Records every call so tests can assert the cache actually
    prevents re-fetching."""

    responses: dict[str, dict]
    calls: list[str] = field(default_factory=list)

    def get(self, url: str, *, params: dict | None = None, timeout: float | None = None) -> FakeResponse:
        self.calls.append(url)
        if params:
            key = f"{url}?{params.get('q', '')}"
        else:
            key = url
        if key not in self.responses:
            raise AssertionError(f"FakeHttpClient got an unexpected request: {key}")
        return FakeResponse(self.responses[key])


def _make_client() -> FakeHttpClient:
    return FakeHttpClient(
        responses={
            "https://spansh.co.uk/api/systems/field_values/system_names?Sol": SOL_LOOKUP_RESPONSE,
            "https://www.spansh.co.uk/api/system/10477373803": SOL_SYSTEM_RESPONSE,
        }
    )


class TestGetOrFetchSystem:
    def test_cache_miss_fetches_and_persists(self, db_session):
        client = _make_client()

        result = get_or_fetch_system(db_session, "Sol", client)

        assert result is not None
        assert result.system_address == 10477373803
        assert len(client.calls) == 2  # name lookup + system dump

        assert db_session.query(System).count() == 1
        assert db_session.query(Body).count() == 1
        assert db_session.query(Station).count() == 1

    def test_cache_hit_makes_no_network_call(self, db_session):
        client = _make_client()
        get_or_fetch_system(db_session, "Sol", client)  # populate cache
        assert len(client.calls) == 2

        result = get_or_fetch_system(db_session, "Sol", client)  # should hit cache

        assert result is not None
        assert result.system_address == 10477373803
        assert len(client.calls) == 2  # unchanged — no new network calls

    def test_unknown_system_returns_none_without_crashing(self, db_session):
        client = FakeHttpClient(responses={"https://spansh.co.uk/api/systems/field_values/system_names?Nowhere": {"min_max": []}})

        result = get_or_fetch_system(db_session, "Nowhere", client)

        assert result is None
        assert db_session.query(System).count() == 0
