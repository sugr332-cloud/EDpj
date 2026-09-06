from __future__ import annotations

import datetime as dt

from app.backtest.formula_validation import GateVerdict
from app.bio.species_prediction import BodyRecord
from app.bio.species_value_master import get_species_value
from app.bio.value_formula_backtest import compute_actual_value, compute_expected_value, run_value_formula_backtest
from app.db.models.edsm import BodyPhysicalParameters

T0 = dt.datetime(2026, 8, 20, tzinfo=dt.timezone.utc)

STRATUM_TECTONICAS = "$Codex_Ent_Stratum_07_Name;"  # 19,010,800 in the real master
BACTERIUM_AURASUS = "$Codex_Ent_Bacterial_01_Name;"  # 1,000,000 in the real master
UNKNOWN_SPECIES = "$Codex_Ent_Totally_Fake_Name;"


def _params(session, system_address, body_id, gravity=1.0, temp=200, atmosphere="Thin", volcanism="None", sub_type="Rocky body"):
    session.add(
        BodyPhysicalParameters(
            system_address=system_address, body_id=body_id, gravity=gravity, surface_temperature=temp,
            atmosphere_type=atmosphere, volcanism_type=volcanism, sub_type=sub_type,
        )
    )
    session.commit()


class TestComputeExpectedValue:
    def test_sums_probability_weighted_value(self):
        distribution = {STRATUM_TECTONICAS: 0.5, BACTERIUM_AURASUS: 0.5}
        expected = 0.5 * 19010800 + 0.5 * 1000000
        assert compute_expected_value(distribution) == expected

    def test_none_when_no_species_in_master(self):
        assert compute_expected_value({UNKNOWN_SPECIES: 1.0}) is None

    def test_partial_coverage_sums_only_known_species(self):
        distribution = {STRATUM_TECTONICAS: 0.5, UNKNOWN_SPECIES: 0.5}
        assert compute_expected_value(distribution) == 0.5 * 19010800


class TestComputeActualValue:
    def test_sums_master_values_for_observed_species(self):
        assert compute_actual_value(frozenset({STRATUM_TECTONICAS, BACTERIUM_AURASUS})) == 19010800 + 1000000

    def test_none_when_no_species_known(self):
        assert compute_actual_value(frozenset({UNKNOWN_SPECIES})) is None

    def test_unknown_species_in_the_set_is_silently_skipped_not_zeroed(self):
        assert compute_actual_value(frozenset({STRATUM_TECTONICAS, UNKNOWN_SPECIES})) == 19010800


class TestRunValueFormulaBacktest:
    def test_perfect_prediction_scores_a_hit(self, db_session):
        # fit population entirely one species at the same environment as
        # the holdout target -> predicted distribution is 100% that
        # species, matching the holdout body's own actual species exactly.
        _params(db_session, 1, 1, gravity=1.0, temp=200)
        _params(db_session, 1, 2, gravity=1.0, temp=200)
        fit = {(1, 1): BodyRecord(first_observed_at=T0, species=frozenset({STRATUM_TECTONICAS}))}
        holdout = {(1, 2): BodyRecord(first_observed_at=T0, species=frozenset({STRATUM_TECTONICAS}))}

        result = run_value_formula_backtest(db_session, fit, holdout, minimum_cases=1)

        assert result.verdict == GateVerdict.PASS
        assert result.formula_accuracy == 1.0

    def test_insufficient_when_below_minimum_cases(self, db_session):
        _params(db_session, 1, 1, gravity=1.0, temp=200)
        _params(db_session, 1, 2, gravity=1.0, temp=200)
        fit = {(1, 1): BodyRecord(first_observed_at=T0, species=frozenset({STRATUM_TECTONICAS}))}
        holdout = {(1, 2): BodyRecord(first_observed_at=T0, species=frozenset({STRATUM_TECTONICAS}))}

        result = run_value_formula_backtest(db_session, fit, holdout, minimum_cases=5)

        assert result.verdict == GateVerdict.INSUFFICIENT

    def test_holdout_body_with_no_edsm_params_is_excluded(self, db_session):
        _params(db_session, 1, 1, gravity=1.0, temp=200)
        fit = {(1, 1): BodyRecord(first_observed_at=T0, species=frozenset({STRATUM_TECTONICAS}))}
        holdout = {(1, 2): BodyRecord(first_observed_at=T0, species=frozenset({STRATUM_TECTONICAS}))}  # no params cached

        result = run_value_formula_backtest(db_session, fit, holdout, minimum_cases=1)

        assert result.verdict == GateVerdict.INSUFFICIENT
        assert result.valid_cases == 0

    def test_body_whose_actual_species_has_no_master_value_is_excluded(self, db_session):
        _params(db_session, 1, 1, gravity=1.0, temp=200)
        _params(db_session, 1, 2, gravity=1.0, temp=200)
        fit = {(1, 1): BodyRecord(first_observed_at=T0, species=frozenset({STRATUM_TECTONICAS}))}
        holdout = {(1, 2): BodyRecord(first_observed_at=T0, species=frozenset({UNKNOWN_SPECIES}))}

        result = run_value_formula_backtest(db_session, fit, holdout, minimum_cases=1)

        assert result.verdict == GateVerdict.INSUFFICIENT

    def test_multi_species_body_uses_marginal_membership_not_a_normalized_share(self, db_session):
        # Regression test for the real-data FAIL (30.4%, 401 cases) traced
        # to predict_knn_distribution's Sigma p(s)=1 constraint diluting
        # multi-species bodies. With marginal membership probabilities, a
        # fit body identical in both species and environment to the
        # holdout body should make each species independently p=1.0, so
        # the predicted sum equals the true sum exactly.
        _params(db_session, 1, 1, gravity=1.0, temp=200)
        _params(db_session, 1, 2, gravity=1.0, temp=200)
        both_species = frozenset({STRATUM_TECTONICAS, BACTERIUM_AURASUS})
        fit = {(1, 1): BodyRecord(first_observed_at=T0, species=both_species)}
        holdout = {(1, 2): BodyRecord(first_observed_at=T0, species=both_species)}

        result = run_value_formula_backtest(db_session, fit, holdout, minimum_cases=1)

        assert result.verdict == GateVerdict.PASS
        assert result.formula_accuracy == 1.0
