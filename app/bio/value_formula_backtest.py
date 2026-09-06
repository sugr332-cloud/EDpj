"""Bio Value Formula Backtest.

Spec (docs/BIO_EXTERNAL_DATA_VALIDATION_SPEC_V0.1.md §5/§6.2,
docs/PHASE_BIO_SPECIES_PREDICTION_BACKTEST_DESIGN_BASELINE_V0.1.md §5).
Deliberately kept in its OWN module, independent of
app/bio/species_prediction.py's own accuracy accounting (top-1/top-k/
coverage) -- species-prediction error and fixed-value error must never
be conflated (spec §4.3). This module only asks: given the species
probability distribution app.bio.species_prediction already produces,
does `expected_value_base = sum(p(s) * base_value(s))` come reasonably
close to what the body was actually worth (the SpeciesValueMaster
value of the species genuinely observed there)?

`p(s)` here is a per-species MARGINAL "is species s present on this
body" probability (predict_species_membership_probabilities), not a
single normalized categorical share -- Sigma p(s) is NOT required to
equal 1, since a body can genuinely host several species at once and
the ground truth (compute_actual_value) sums all of their master
values. An earlier version of this module used the normalized
categorical distribution instead and FAILed the 60% gate at 30.4%
(401 valid cases); real-data audit traced this to systematic
under-prediction on multi-species bodies (17.3% hit-rate vs 47.4% on
single-species bodies) caused by exactly this Sigma=1 constraint.

Reuses app.backtest.formula_validation's generic accuracy-gate math
(relative_error/hit-rate, the same 60%/±40% definitions already
governing Mining and Trade Formula Validation) rather than inventing a
second accuracy definition for Bio.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.backtest.formula_validation import EvaluationCase, FormulaAccuracyResult, compute_formula_accuracy
from app.bio.body_parameters import get_body_parameters
from app.bio.species_prediction import BodyFeatures, BodyKey, BodyRecord, predict_species_membership_probabilities
from app.bio.species_value_master import get_species_value


def compute_expected_value(distribution: dict[str, float]) -> float | None:
    """Sum(p(s) * base_value(s)) over species the master actually
    covers. None (not a partial guess) when NONE of the predicted
    species have a master entry -- a real but incomplete estimate (some
    covered, some not) still returns the partial sum over what IS
    known, consistent with the rest of this project never fabricating
    the unknown portion as zero."""
    total = 0.0
    matched_any = False
    for species, probability in distribution.items():
        entry = get_species_value(species)
        if entry is None:
            continue
        total += probability * entry.value
        matched_any = True
    return total if matched_any else None


def compute_actual_value(actual_species: frozenset[str]) -> float | None:
    """Sum of SpeciesValueMaster values for every species genuinely
    observed on this body -- the ground truth `expected_value_base` is
    being checked against. None when none of the actually-observed
    species have a master entry (can't reconstruct a ground truth at
    all for this body, not "worth zero")."""
    known_values = [entry.value for s in actual_species if (entry := get_species_value(s)) is not None]
    return sum(known_values) if known_values else None


def run_value_formula_backtest(
    session: Session,
    fit_population: dict[BodyKey, BodyRecord],
    holdout_population: dict[BodyKey, BodyRecord],
    minimum_cases: int,
) -> FormulaAccuracyResult:
    """Same fit-population k-NN reference set as
    app.bio.species_prediction.run_baseline1 -- built independently
    here (not imported from run_baseline1) so this module's own
    accuracy accounting never shares state with the species-prediction
    backtest's, per the design doc's "independent code path"
    requirement."""
    fit_examples: list[tuple[BodyFeatures, frozenset[str]]] = []
    for key, record in fit_population.items():
        params = get_body_parameters(session, key[0], key[1])
        if params is None or params.gravity is None or params.surface_temperature is None:
            continue
        fit_examples.append(
            (
                BodyFeatures(
                    gravity=params.gravity, surface_temperature=params.surface_temperature,
                    atmosphere_type=params.atmosphere_type, volcanism_type=params.volcanism_type,
                    sub_type=params.sub_type,
                ),
                record.species,
            )
        )

    cases: list[EvaluationCase] = []
    for key, record in holdout_population.items():
        params = get_body_parameters(session, key[0], key[1])
        if params is None or params.gravity is None or params.surface_temperature is None:
            continue
        target = BodyFeatures(
            gravity=params.gravity, surface_temperature=params.surface_temperature,
            atmosphere_type=params.atmosphere_type, volcanism_type=params.volcanism_type,
            sub_type=params.sub_type,
        )
        distribution = predict_species_membership_probabilities(target, fit_examples)
        if distribution is None:
            continue
        predicted_value = compute_expected_value(distribution)
        actual_value = compute_actual_value(record.species)
        if predicted_value is None or actual_value is None:
            continue
        cases.append(EvaluationCase(predicted_value=predicted_value, actual_value=actual_value))

    return compute_formula_accuracy(cases, minimum_cases)
