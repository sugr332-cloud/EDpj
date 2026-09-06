"""Value Formula Backtest — extended candidate feature set.

Spec (docs/PHASE_BIO_SPECIES_PREDICTION_BACKTEST_DESIGN_BASELINE_V0.1.md
§5.9). Mirrors app.bio.value_formula_backtest.run_value_formula_backtest
exactly (same EvaluationCase/compute_formula_accuracy gate math, same
fit/holdout population inputs, same minimum_cases contract) but builds
its k-NN reference set from
app.bio.species_prediction_extended.ExtendedBodyFeatures instead of the
frozen 5-feature baseline -- the only deliberate difference, so a
before/after comparison isolates the effect of the candidate feature
set, not some incidental implementation drift.

A fit or holdout body is included here only if all 9 numeric candidate
fields (design doc §5.8) are populated -- consistent with this
project's "never fabricate missing data" convention, same policy the
baseline already applies to gravity/surface_temperature.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.backtest.formula_validation import EvaluationCase, FormulaAccuracyResult, compute_formula_accuracy
from app.bio.body_parameters import get_body_parameters
from app.bio.species_prediction import BodyKey, BodyRecord
from app.bio.species_prediction_extended import ExtendedBodyFeatures, predict_species_membership_probabilities
from app.bio.value_formula_backtest import compute_actual_value, compute_expected_value

_REQUIRED_NUMERIC_COLUMNS = (
    "gravity", "surface_temperature", "earth_masses", "radius", "surface_pressure",
    "distance_to_arrival", "orbital_period", "orbital_eccentricity", "rotational_period",
)


def _extended_features_or_none(session: Session, key: BodyKey) -> ExtendedBodyFeatures | None:
    params = get_body_parameters(session, key[0], key[1])
    if params is None:
        return None
    if any(getattr(params, field) is None for field in _REQUIRED_NUMERIC_COLUMNS):
        return None
    return ExtendedBodyFeatures(
        gravity=params.gravity, surface_temperature=params.surface_temperature,
        atmosphere_type=params.atmosphere_type, volcanism_type=params.volcanism_type, sub_type=params.sub_type,
        earth_masses=params.earth_masses, radius=params.radius, surface_pressure=params.surface_pressure,
        terraforming_state=params.terraforming_state, distance_to_arrival=params.distance_to_arrival,
        orbital_period=params.orbital_period, orbital_eccentricity=params.orbital_eccentricity,
        rotational_period=params.rotational_period,
        atmosphere_composition=params.atmosphere_composition, solid_composition=params.solid_composition,
    )


def run_extended_value_formula_backtest(
    session: Session,
    fit_population: dict[BodyKey, BodyRecord],
    holdout_population: dict[BodyKey, BodyRecord],
    minimum_cases: int,
) -> FormulaAccuracyResult:
    fit_examples: list[tuple[ExtendedBodyFeatures, frozenset[str]]] = []
    for key, record in fit_population.items():
        features = _extended_features_or_none(session, key)
        if features is None:
            continue
        fit_examples.append((features, record.species))

    cases: list[EvaluationCase] = []
    for key, record in holdout_population.items():
        target = _extended_features_or_none(session, key)
        if target is None:
            continue
        distribution = predict_species_membership_probabilities(target, fit_examples)
        if distribution is None:
            continue
        predicted_value = compute_expected_value(distribution)
        actual_value = compute_actual_value(record.species)
        if predicted_value is None or actual_value is None:
            continue
        cases.append(EvaluationCase(predicted_value=predicted_value, actual_value=actual_value))

    return compute_formula_accuracy(cases, minimum_cases)
