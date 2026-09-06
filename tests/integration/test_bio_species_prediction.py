from __future__ import annotations

import datetime as dt

from app.bio.species_prediction import (
    BodyFeatures,
    BodyRecord,
    PredictionCase,
    collect_body_population,
    evaluate_predictions,
    predict_knn,
    predict_knn_distribution,
    predict_species_membership_probabilities,
    rank_species_by_frequency,
    run_baseline0,
    run_baseline1,
    split_chronological,
)
from app.db.models.edsm import BodyPhysicalParameters
from app.db.models.eddn import BioObservation

T0 = dt.datetime(2026, 8, 20, tzinfo=dt.timezone.utc)


def _obs(session, system_address, body_id, species, observed_at, genus="$Codex_Ent_Bacterial_Genus_Name;"):
    session.add(
        BioObservation(
            system_address=system_address, body_id=body_id, star_system="Test", genus=genus, species=species,
            variant=None, star_pos_x=0.0, star_pos_y=0.0, star_pos_z=0.0, observed_at=observed_at,
            source="scanorganic_archive",
        )
    )
    session.commit()


def _params(session, system_address, body_id, gravity, temp, atmosphere="Thin", volcanism="None", sub_type="Rocky body"):
    session.add(
        BodyPhysicalParameters(
            system_address=system_address, body_id=body_id, gravity=gravity, surface_temperature=temp,
            atmosphere_type=atmosphere, volcanism_type=volcanism, sub_type=sub_type,
        )
    )
    session.commit()


class TestCollectBodyPopulation:
    def test_earliest_observed_at_is_kept_per_body(self, db_session):
        _obs(db_session, 1, 1, "SpeciesA", T0 + dt.timedelta(days=2))
        _obs(db_session, 1, 1, "SpeciesB", T0)  # earlier, different species -> same body

        population = collect_body_population(db_session)

        record = population[(1, 1)]
        # SQLite doesn't round-trip tzinfo (project-wide known quirk).
        assert record.first_observed_at == T0.replace(tzinfo=None)
        assert record.species == frozenset({"SpeciesA", "SpeciesB"})


class TestSplitChronological:
    def test_splits_by_first_observed_at(self, db_session):
        population = {
            (1, 1): BodyRecord(first_observed_at=T0, species=frozenset({"A"})),
            (1, 2): BodyRecord(first_observed_at=T0 + dt.timedelta(days=10), species=frozenset({"B"})),
        }
        fit, holdout = split_chronological(population, split_at=T0 + dt.timedelta(days=5))
        assert (1, 1) in fit
        assert (1, 2) in holdout

    def test_boundary_is_inclusive_on_the_fit_side(self, db_session):
        population = {(1, 1): BodyRecord(first_observed_at=T0, species=frozenset({"A"}))}
        fit, holdout = split_chronological(population, split_at=T0)
        assert (1, 1) in fit
        assert (1, 1) not in holdout


class TestRankSpeciesByFrequency:
    def test_ranks_most_common_first(self):
        population = {
            (1, 1): BodyRecord(first_observed_at=T0, species=frozenset({"A"})),
            (1, 2): BodyRecord(first_observed_at=T0, species=frozenset({"A", "B"})),
            (1, 3): BodyRecord(first_observed_at=T0, species=frozenset({"B"})),
        }
        ranking = rank_species_by_frequency(population)
        # A appears in 2 bodies, B appears in 2 bodies -- tie broken alphabetically
        assert ranking[0] == "A"

    def test_empty_population_yields_empty_ranking(self):
        assert rank_species_by_frequency({}) == []


class TestPredictKnn:
    def test_no_fit_examples_returns_none(self):
        target = BodyFeatures(gravity=1.0, surface_temperature=200, atmosphere_type="Thin", volcanism_type="None", sub_type="Rocky body")
        assert predict_knn(target, []) is None

    def test_exact_environmental_match_beats_numeric_closeness(self):
        target = BodyFeatures(gravity=1.0, surface_temperature=200, atmosphere_type="CarbonDioxide", volcanism_type="None", sub_type="Rocky body")
        close_numeric_wrong_category = (
            BodyFeatures(gravity=1.01, surface_temperature=201, atmosphere_type="Ammonia", volcanism_type="None", sub_type="Rocky body"),
            frozenset({"WrongSpecies"}),
        )
        farther_numeric_right_category = (
            BodyFeatures(gravity=1.5, surface_temperature=250, atmosphere_type="CarbonDioxide", volcanism_type="None", sub_type="Rocky body"),
            frozenset({"RightSpecies"}),
        )
        result = predict_knn(target, [close_numeric_wrong_category, farther_numeric_right_category], k=1)
        assert result == ["RightSpecies"]

    def test_majority_vote_among_k_neighbors(self):
        target = BodyFeatures(gravity=1.0, surface_temperature=200, atmosphere_type="Thin", volcanism_type="None", sub_type="Rocky body")
        examples = [
            (BodyFeatures(1.0, 200, "Thin", "None", "Rocky body"), frozenset({"A"})),
            (BodyFeatures(1.01, 201, "Thin", "None", "Rocky body"), frozenset({"A"})),
            (BodyFeatures(1.02, 202, "Thin", "None", "Rocky body"), frozenset({"B"})),
        ]
        result = predict_knn(target, examples, k=3)
        assert result[0] == "A"


class TestPredictKnnDistribution:
    def test_no_fit_examples_returns_none(self):
        target = BodyFeatures(gravity=1.0, surface_temperature=200, atmosphere_type="Thin", volcanism_type="None", sub_type="Rocky body")
        assert predict_knn_distribution(target, []) is None

    def test_distribution_sums_to_one(self):
        target = BodyFeatures(gravity=1.0, surface_temperature=200, atmosphere_type="Thin", volcanism_type="None", sub_type="Rocky body")
        examples = [
            (BodyFeatures(1.0, 200, "Thin", "None", "Rocky body"), frozenset({"A"})),
            (BodyFeatures(1.01, 201, "Thin", "None", "Rocky body"), frozenset({"A"})),
            (BodyFeatures(1.02, 202, "Thin", "None", "Rocky body"), frozenset({"B"})),
        ]
        dist = predict_knn_distribution(target, examples, k=3)
        assert abs(sum(dist.values()) - 1.0) < 1e-9
        assert dist["A"] == 2 / 3
        assert dist["B"] == 1 / 3

    def test_multi_species_neighbor_contributes_to_each_of_its_species(self):
        target = BodyFeatures(gravity=1.0, surface_temperature=200, atmosphere_type="Thin", volcanism_type="None", sub_type="Rocky body")
        examples = [(BodyFeatures(1.0, 200, "Thin", "None", "Rocky body"), frozenset({"A", "B"}))]
        dist = predict_knn_distribution(target, examples, k=1)
        assert dist == {"A": 0.5, "B": 0.5}


class TestPredictSpeciesMembershipProbabilities:
    def test_no_fit_examples_returns_none(self):
        target = BodyFeatures(gravity=1.0, surface_temperature=200, atmosphere_type="Thin", volcanism_type="None", sub_type="Rocky body")
        assert predict_species_membership_probabilities(target, []) is None

    def test_probabilities_need_not_sum_to_one(self):
        # every neighbor shares the same 2 species -> both are near-certain
        # simultaneously, unlike predict_knn_distribution's normalized share.
        target = BodyFeatures(gravity=1.0, surface_temperature=200, atmosphere_type="Thin", volcanism_type="None", sub_type="Rocky body")
        examples = [
            (BodyFeatures(1.0, 200, "Thin", "None", "Rocky body"), frozenset({"A", "B"})),
            (BodyFeatures(1.01, 201, "Thin", "None", "Rocky body"), frozenset({"A", "B"})),
        ]
        dist = predict_species_membership_probabilities(target, examples, k=2)
        assert dist == {"A": 1.0, "B": 1.0}
        assert sum(dist.values()) == 2.0

    def test_partial_co_occurrence_gives_fractional_membership(self):
        target = BodyFeatures(gravity=1.0, surface_temperature=200, atmosphere_type="Thin", volcanism_type="None", sub_type="Rocky body")
        examples = [
            (BodyFeatures(1.0, 200, "Thin", "None", "Rocky body"), frozenset({"A"})),
            (BodyFeatures(1.01, 201, "Thin", "None", "Rocky body"), frozenset({"A", "B"})),
        ]
        dist = predict_species_membership_probabilities(target, examples, k=2)
        assert dist == {"A": 1.0, "B": 0.5}

    def test_denominator_is_actual_neighbor_count_not_requested_k(self):
        # only 1 fit example available even though k=5 is requested.
        target = BodyFeatures(gravity=1.0, surface_temperature=200, atmosphere_type="Thin", volcanism_type="None", sub_type="Rocky body")
        examples = [(BodyFeatures(1.0, 200, "Thin", "None", "Rocky body"), frozenset({"A"}))]
        dist = predict_species_membership_probabilities(target, examples, k=5)
        assert dist == {"A": 1.0}


class TestEvaluatePredictions:
    def test_top1_hit_and_miss(self):
        cases = [
            PredictionCase(key=(1, 1), actual_species=frozenset({"A"}), predicted=["A", "B"]),
            PredictionCase(key=(1, 2), actual_species=frozenset({"C"}), predicted=["A", "B"]),
        ]
        result = evaluate_predictions(cases)
        assert result.top1_hits == 1
        assert result.top1_accuracy == 0.5

    def test_topk_hit_counts_any_of_the_top_k(self):
        cases = [PredictionCase(key=(1, 1), actual_species=frozenset({"B"}), predicted=["A", "B", "C"])]
        result = evaluate_predictions(cases, top_k=3)
        assert result.topk_hits == 1
        assert result.top1_hits == 0  # top-1 alone (A) doesn't match

    def test_insufficient_cases_excluded_from_accuracy_denominator(self):
        cases = [
            PredictionCase(key=(1, 1), actual_species=frozenset({"A"}), predicted=["A"]),
            PredictionCase(key=(1, 2), actual_species=frozenset({"B"}), predicted=None),
        ]
        result = evaluate_predictions(cases)
        assert result.predicted_count == 1
        assert result.insufficient_count == 1
        assert result.top1_accuracy == 1.0  # only the predicted case counts
        assert result.coverage == 0.5

    def test_all_insufficient_never_fabricates_an_accuracy(self):
        cases = [PredictionCase(key=(1, 1), actual_species=frozenset({"A"}), predicted=None)]
        result = evaluate_predictions(cases)
        assert result.top1_accuracy is None
        assert result.topk_hit_rate is None


class TestRunBaseline0:
    def test_constant_prediction_scored_against_holdout(self):
        fit = {
            (1, 1): BodyRecord(first_observed_at=T0, species=frozenset({"A"})),
            (1, 2): BodyRecord(first_observed_at=T0, species=frozenset({"A"})),
        }
        holdout = {(1, 3): BodyRecord(first_observed_at=T0, species=frozenset({"A"}))}
        result = run_baseline0(fit, holdout)
        assert result.top1_accuracy == 1.0

    def test_empty_fit_population_is_insufficient_for_every_holdout_body(self):
        holdout = {(1, 1): BodyRecord(first_observed_at=T0, species=frozenset({"A"}))}
        result = run_baseline0({}, holdout)
        assert result.insufficient_count == 1
        assert result.top1_accuracy is None


class TestRunBaseline1:
    def test_uses_cached_edsm_parameters_for_fit_and_holdout(self, db_session):
        _params(db_session, 1, 1, gravity=1.0, temp=200)
        _params(db_session, 1, 2, gravity=1.01, temp=201)
        fit = {(1, 1): BodyRecord(first_observed_at=T0, species=frozenset({"A"}))}
        holdout = {(1, 2): BodyRecord(first_observed_at=T0, species=frozenset({"A"}))}

        result = run_baseline1(db_session, fit, holdout)

        assert result.top1_accuracy == 1.0

    def test_holdout_body_with_no_cached_parameters_is_insufficient(self, db_session):
        _params(db_session, 1, 1, gravity=1.0, temp=200)
        fit = {(1, 1): BodyRecord(first_observed_at=T0, species=frozenset({"A"}))}
        holdout = {(1, 2): BodyRecord(first_observed_at=T0, species=frozenset({"A"}))}  # no params cached

        result = run_baseline1(db_session, fit, holdout)

        assert result.insufficient_count == 1
        assert result.top1_accuracy is None
