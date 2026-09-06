from __future__ import annotations

import datetime as dt

from app.backtest.formula_validation import GateVerdict
from app.bio.species_prediction import BodyRecord
from app.bio.value_formula_backtest_extended import run_extended_value_formula_backtest
from app.db.models.edsm import BodyPhysicalParameters

T0 = dt.datetime(2026, 8, 20, tzinfo=dt.timezone.utc)

STRATUM_TECTONICAS = "$Codex_Ent_Stratum_07_Name;"  # 19,010,800 in the real master


def _full_params(session, system_address, body_id, **overrides):
    defaults = dict(
        system_address=system_address, body_id=body_id, gravity=1.0, surface_temperature=200,
        atmosphere_type="Thin", volcanism_type="None", sub_type="Rocky body",
        earth_masses=0.1, radius=3000.0, surface_pressure=0.01, terraforming_state="Not terraformable",
        distance_to_arrival=500.0, orbital_period=100.0, orbital_eccentricity=0.01, rotational_period=1.0,
    )
    defaults.update(overrides)
    session.add(BodyPhysicalParameters(**defaults))
    session.commit()


class TestRunExtendedValueFormulaBacktest:
    def test_perfect_prediction_scores_a_hit(self, db_session):
        _full_params(db_session, 1, 1)
        _full_params(db_session, 1, 2)
        fit = {(1, 1): BodyRecord(first_observed_at=T0, species=frozenset({STRATUM_TECTONICAS}))}
        holdout = {(1, 2): BodyRecord(first_observed_at=T0, species=frozenset({STRATUM_TECTONICAS}))}

        result = run_extended_value_formula_backtest(db_session, fit, holdout, minimum_cases=1)

        assert result.verdict == GateVerdict.PASS
        assert result.formula_accuracy == 1.0

    def test_body_missing_a_required_numeric_field_is_excluded(self, db_session):
        _full_params(db_session, 1, 1)
        _full_params(db_session, 1, 2, earth_masses=None)  # missing one of the 9 required fields
        fit = {(1, 1): BodyRecord(first_observed_at=T0, species=frozenset({STRATUM_TECTONICAS}))}
        holdout = {(1, 2): BodyRecord(first_observed_at=T0, species=frozenset({STRATUM_TECTONICAS}))}

        result = run_extended_value_formula_backtest(db_session, fit, holdout, minimum_cases=1)

        assert result.verdict == GateVerdict.INSUFFICIENT
        assert result.valid_cases == 0

    def test_no_cached_parameters_is_insufficient(self, db_session):
        _full_params(db_session, 1, 1)
        fit = {(1, 1): BodyRecord(first_observed_at=T0, species=frozenset({STRATUM_TECTONICAS}))}
        holdout = {(1, 2): BodyRecord(first_observed_at=T0, species=frozenset({STRATUM_TECTONICAS}))}  # no params cached

        result = run_extended_value_formula_backtest(db_session, fit, holdout, minimum_cases=1)

        assert result.verdict == GateVerdict.INSUFFICIENT
