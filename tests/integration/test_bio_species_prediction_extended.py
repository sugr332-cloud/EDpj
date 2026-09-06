from __future__ import annotations

from app.bio.species_prediction_extended import ExtendedBodyFeatures, predict_species_membership_probabilities


def _features(**overrides) -> ExtendedBodyFeatures:
    base = dict(
        gravity=1.0, surface_temperature=200.0, atmosphere_type="Thin", volcanism_type="None", sub_type="Rocky body",
        earth_masses=0.1, radius=3000.0, surface_pressure=0.01, terraforming_state="Not terraformable",
        distance_to_arrival=500.0, orbital_period=100.0, orbital_eccentricity=0.01, rotational_period=1.0,
        atmosphere_composition=None, solid_composition=None,
    )
    base.update(overrides)
    return ExtendedBodyFeatures(**base)


class TestPredictSpeciesMembershipProbabilities:
    def test_no_fit_examples_returns_none(self):
        target = _features()
        assert predict_species_membership_probabilities(target, []) is None

    def test_identical_neighbors_give_full_membership(self):
        target = _features()
        examples = [(_features(), frozenset({"A", "B"})), (_features(), frozenset({"A", "B"}))]
        dist = predict_species_membership_probabilities(target, examples, k=2)
        assert dist == {"A": 1.0, "B": 1.0}

    def test_exact_categorical_match_beats_close_numeric_mismatch(self):
        target = _features(atmosphere_type="CarbonDioxide")
        close_numeric_wrong_category = (
            _features(gravity=1.001, atmosphere_type="Ammonia"), frozenset({"WrongSpecies"}),
        )
        farther_numeric_right_category = (
            _features(gravity=5.0, atmosphere_type="CarbonDioxide"), frozenset({"RightSpecies"}),
        )
        dist = predict_species_membership_probabilities(
            target, [close_numeric_wrong_category, farther_numeric_right_category], k=1
        )
        assert dist == {"RightSpecies": 1.0}

    def test_composition_difference_affects_distance_ranking(self):
        target = _features(atmosphere_composition={"Carbon dioxide": 100.0})
        same_composition = (
            _features(atmosphere_composition={"Carbon dioxide": 100.0}), frozenset({"SameComp"}),
        )
        different_composition = (
            _features(atmosphere_composition={"Sulphur dioxide": 100.0}), frozenset({"DiffComp"}),
        )
        dist = predict_species_membership_probabilities(target, [same_composition, different_composition], k=1)
        assert dist == {"SameComp": 1.0}

    def test_missing_composition_on_either_side_is_neutral_not_a_mismatch(self):
        # target has a composition, one neighbor doesn't -- should not be
        # penalized as if it were maximally different.
        target = _features(atmosphere_composition={"Carbon dioxide": 100.0})
        no_composition_neighbor = (_features(atmosphere_composition=None, gravity=1.0), frozenset({"A"}))
        far_numeric_neighbor = (_features(atmosphere_composition={"Carbon dioxide": 100.0}, gravity=50.0), frozenset({"B"}))
        dist = predict_species_membership_probabilities(target, [no_composition_neighbor, far_numeric_neighbor], k=1)
        assert dist == {"A": 1.0}
