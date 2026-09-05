from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.state import get_session
from app.db.models.player import SINGLETON_ID, CargoState, PlayerState

NOW = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_session] = lambda: db_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _seed_player_state(session) -> None:
    session.add(
        PlayerState(
            id=SINGLETON_ID,
            current_system="Deciat",
            current_system_address=123456789,
            current_body_id=1,
            current_body_name="Deciat A",
            current_station_id=128666762,
            current_station_name="Farseer Inc",
            current_ship_id=1,
            credits=950000,
            fuel_main=8.0,
            cargo_tons=5,
            docked=True,
            landed=False,
            on_foot=False,
            source_status={"status_json": "ok", "cargo_json": "ok"},
            updated_at=NOW,
        )
    )
    session.add(CargoState(commodity_name="platinum", quantity=5, updated_at=NOW))
    session.commit()


class TestGetState:
    def test_returns_current_player_state(self, client, db_session):
        _seed_player_state(db_session)

        response = client.get("/api/state")

        assert response.status_code == 200
        body = response.json()
        assert body["current_system"] == "Deciat"
        assert body["current_station_id"] == 128666762
        assert body["docked"] is True
        assert body["credits"] == 950000

    def test_404_when_no_state_yet(self, client):
        response = client.get("/api/state")
        assert response.status_code == 404


class TestGetShip:
    def test_returns_current_ship_id(self, client, db_session):
        _seed_player_state(db_session)
        response = client.get("/api/state/ship")
        assert response.status_code == 200
        assert response.json()["current_ship_id"] == 1


class TestGetCargo:
    def test_returns_cargo_items(self, client, db_session):
        _seed_player_state(db_session)
        response = client.get("/api/state/cargo")
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["commodity_name"] == "platinum"
        assert body[0]["quantity"] == 5

    def test_empty_cargo_returns_empty_list_not_404(self, client, db_session):
        db_session.add(
            PlayerState(id=SINGLETON_ID, docked=False, landed=False, on_foot=False, source_status={}, updated_at=NOW)
        )
        db_session.commit()

        response = client.get("/api/state/cargo")
        assert response.status_code == 200
        assert response.json() == []
