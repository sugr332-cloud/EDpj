from __future__ import annotations

from dataclasses import dataclass, field

from app.bio.body_parameters import backfill_extended_parameters, ensure_body_parameters_cached, get_body_parameters
from app.db.models.edsm import BodyPhysicalParameters

DECIAT_BODIES_RESPONSE = {
    "id": 1547,
    "id64": 6681123623626,
    "name": "Deciat",
    "bodyCount": 2,
    "bodies": [
        {"id": 3984, "bodyId": 0, "name": "Deciat", "type": "Star", "subType": "K (Yellow-Orange) Star"},
        {
            "id": 1901, "bodyId": 11, "name": "Deciat 1", "type": "Planet", "subType": "Metal-rich body",
            "gravity": 1.2086911843193298, "surfaceTemperature": 1006, "atmosphereType": "No atmosphere",
            "volcanismType": "Minor Metallic Magma",
        },
    ],
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
    responses: dict[str, dict]
    calls: list[str] = field(default_factory=list)

    def get(self, url: str, *, params: dict | None = None, timeout: float | None = None) -> FakeResponse:
        key = f"{url}?{params.get('systemName', '')}" if params else url
        self.calls.append(key)
        if key not in self.responses:
            raise AssertionError(f"unexpected request: {key}")
        return FakeResponse(self.responses[key])


def _client(responses: dict[str, dict]) -> FakeHttpClient:
    return FakeHttpClient(responses=responses)


class TestEnsureBodyParametersCached:
    def test_caches_every_body_from_one_request(self, db_session):
        client = _client({"https://www.edsm.net/api-system-v1/bodies?Deciat": DECIAT_BODIES_RESPONSE})

        ensure_body_parameters_cached(db_session, 6681123623626, "Deciat", client)

        rows = db_session.query(BodyPhysicalParameters).filter_by(system_address=6681123623626).all()
        assert len(rows) == 2
        planet = get_body_parameters(db_session, 6681123623626, 11)
        assert planet.gravity == 1.2086911843193298
        assert planet.surface_temperature == 1006
        assert planet.atmosphere_type == "No atmosphere"
        assert planet.volcanism_type == "Minor Metallic Magma"

    def test_cache_hit_does_not_refetch(self, db_session):
        client = _client({"https://www.edsm.net/api-system-v1/bodies?Deciat": DECIAT_BODIES_RESPONSE})
        ensure_body_parameters_cached(db_session, 6681123623626, "Deciat", client)

        ensure_body_parameters_cached(db_session, 6681123623626, "Deciat", client)

        assert len(client.calls) == 1

    def test_system_with_no_edsm_data_is_not_an_error(self, db_session):
        client = _client({"https://www.edsm.net/api-system-v1/bodies?Nowhere": {}})

        ensure_body_parameters_cached(db_session, 999, "Nowhere", client)

        assert get_body_parameters(db_session, 999, 0) is None

    def test_get_body_parameters_returns_none_when_not_cached(self, db_session):
        assert get_body_parameters(db_session, 123, 5) is None

    def test_body_with_null_body_id_is_skipped_not_inserted(self, db_session):
        # A real EDSM response was found to include "bodyId": null for at
        # least one body (e.g. an unresolved star) per system -- must be
        # filtered out, not inserted as a fabricated NULL primary key.
        response = {
            "bodies": [
                {"id": 1, "bodyId": None, "name": "Some Star", "type": "Star"},
                {"id": 2, "bodyId": 1, "name": "Some Planet", "type": "Planet", "gravity": 1.0, "surfaceTemperature": 300},
            ]
        }
        client = _client({"https://www.edsm.net/api-system-v1/bodies?Somewhere": response})

        ensure_body_parameters_cached(db_session, 42, "Somewhere", client)

        rows = db_session.query(BodyPhysicalParameters).filter_by(system_address=42).all()
        assert len(rows) == 1
        assert rows[0].body_id == 1

    def test_extracts_extended_candidate_features(self, db_session):
        response = {
            "bodies": [
                {
                    "id": 1901, "bodyId": 11, "name": "Deciat 1", "type": "Planet", "subType": "Metal-rich body",
                    "gravity": 1.2, "surfaceTemperature": 1006, "atmosphereType": "No atmosphere",
                    "volcanismType": "Minor Metallic Magma", "earthMasses": 0.5, "radius": 3000.0,
                    "surfacePressure": 0.01, "atmosphereComposition": {"Carbon dioxide": 100.0},
                    "solidComposition": {"Rock": 70.0, "Metal": 30.0}, "terraformingState": "Not terraformable",
                    "distanceToArrival": 500.0, "orbitalPeriod": 100.0, "orbitalEccentricity": 0.01,
                    "rotationalPeriod": 2.0, "materials": {"Iron": 20.0, "Nickel": 15.0},
                },
            ]
        }
        client = _client({"https://www.edsm.net/api-system-v1/bodies?Deciat": response})

        ensure_body_parameters_cached(db_session, 1, "Deciat", client)

        row = get_body_parameters(db_session, 1, 11)
        assert row.earth_masses == 0.5
        assert row.radius == 3000.0
        assert row.surface_pressure == 0.01
        assert row.atmosphere_composition == {"Carbon dioxide": 100.0}
        assert row.solid_composition == {"Rock": 70.0, "Metal": 30.0}
        assert row.terraforming_state == "Not terraformable"
        assert row.distance_to_arrival == 500.0
        assert row.orbital_period == 100.0
        assert row.orbital_eccentricity == 0.01
        assert row.rotational_period == 2.0
        assert row.materials == {"Iron": 20.0, "Nickel": 15.0}


class TestBackfillExtendedParameters:
    def test_updates_only_extended_columns_on_already_cached_row(self, db_session):
        initial_response = {
            "bodies": [
                {"id": 1901, "bodyId": 11, "name": "Deciat 1", "type": "Planet", "subType": "Metal-rich body",
                 "gravity": 1.2, "surfaceTemperature": 1006, "atmosphereType": "No atmosphere",
                 "volcanismType": "Minor Metallic Magma"},
            ]
        }
        client = _client({"https://www.edsm.net/api-system-v1/bodies?Deciat": initial_response})
        ensure_body_parameters_cached(db_session, 1, "Deciat", client)

        backfill_response = {
            "bodies": [
                {"id": 1901, "bodyId": 11, "name": "Deciat 1", "type": "Planet", "subType": "Metal-rich body",
                 "gravity": 1.2, "surfaceTemperature": 1006, "atmosphereType": "No atmosphere",
                 "volcanismType": "Minor Metallic Magma", "earthMasses": 0.5, "radius": 3000.0},
            ]
        }
        client2 = _client({"https://www.edsm.net/api-system-v1/bodies?Deciat": backfill_response})

        updated = backfill_extended_parameters(db_session, 1, "Deciat", client2)

        assert updated == 1
        row = get_body_parameters(db_session, 1, 11)
        assert row.earth_masses == 0.5
        assert row.radius == 3000.0
        assert row.gravity == 1.2  # core column untouched, still correct

    def test_no_edsm_data_returns_zero_updated(self, db_session):
        client = _client({"https://www.edsm.net/api-system-v1/bodies?Nowhere": {}})

        updated = backfill_extended_parameters(db_session, 999, "Nowhere", client)

        assert updated == 0
