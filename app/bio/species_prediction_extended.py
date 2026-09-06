"""Extended-feature k-NN candidate model — multivariate combination test.

Spec (docs/PHASE_BIO_SPECIES_PREDICTION_BACKTEST_DESIGN_BASELINE_V0.1.md
§5.7-§5.9). The frozen baseline (app/bio/species_prediction.py's
BodyFeatures/predict_species_membership_probabilities, 5 features:
gravity, surface_temperature, atmosphere_type, volcanism_type,
sub_type) scored 58.4% on the Value Formula Backtest -- FAIL. A
neighbor audit (§5.7) found the distance calculation on those 5
features works correctly (near-zero distance, zero categorical
mismatches on the worst over-prediction cases) yet species composition
still diverges. A univariate check of 10 EDSM fields not previously
used (§5.9) found none of them individually correlates with which
cases become misses (e.g. distance_to_arrival: 31.7% outlier rate in
misses vs 34.0% in the whole holdout -- no differential signal).

This module tests whether the candidate fields have a COMBINED
(multivariate) effect that a one-at-a-time check cannot see. It is a
deliberately separate module from species_prediction.py: the original
5-feature model and its 58.4% result must remain exactly reproducible
as the frozen comparison baseline (design doc §5.7's explicit
instruction), not silently altered by this experiment.

Candidate feature set (design doc §5.8's priority list, "materials"
excluded per that same doc -- causal link to species presence
unassessed):
  numeric (9, min-max normalized, combined via Euclidean sum-of-squares
  same as the baseline's 2): gravity, surface_temperature, earth_masses,
  radius, surface_pressure, distance_to_arrival, orbital_period,
  orbital_eccentricity, rotational_period
  categorical (4, flat CATEGORICAL_MISMATCH_PENALTY per mismatch, same
  constant as the baseline -- still >> sqrt(9) the new numeric-distance
  ceiling, so categorical exact-matches still dominate): atmosphere_type,
  volcanism_type, sub_type, terraforming_state
  composition (2, L1 distance over the two dicts divided by 200 -- the
  maximum possible L1 distance between two 0-100 compositions --
  treated as one more squared term in the same sum-of-squares; a
  missing composition on either side contributes 0, i.e. neutral, not
  an automatic mismatch, since not every body type carries one):
  atmosphere_composition, solid_composition

A candidate body (fit or holdout) is only usable here if ALL 9 numeric
fields are non-null -- consistent with this project's "never fabricate
missing data" convention, same policy the baseline already applies to
gravity/surface_temperature. Composition dicts are allowed to be
missing (neutral contribution) since they are not populated for every
body type in EDSM's response, whereas the 9 numeric fields are the
actual candidate set under test here.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from app.bio.species_prediction import CATEGORICAL_MISMATCH_PENALTY, NEIGHBOR_COUNT

_NUMERIC_FIELDS = (
    "gravity", "surface_temperature", "earth_masses", "radius", "surface_pressure",
    "distance_to_arrival", "orbital_period", "orbital_eccentricity", "rotational_period",
)
_CATEGORICAL_FIELDS = ("atmosphere_type", "volcanism_type", "sub_type", "terraforming_state")
_COMPOSITION_FIELDS = ("atmosphere_composition", "solid_composition")

_MAX_COMPOSITION_L1_DISTANCE = 200.0  # two 0-100 percentage dicts, worst case fully disjoint


@dataclass(frozen=True)
class ExtendedBodyFeatures:
    gravity: float
    surface_temperature: float
    atmosphere_type: str | None
    volcanism_type: str | None
    sub_type: str | None
    earth_masses: float
    radius: float
    surface_pressure: float
    terraforming_state: str | None
    distance_to_arrival: float
    orbital_period: float
    orbital_eccentricity: float
    rotational_period: float
    atmosphere_composition: dict[str, float] | None
    solid_composition: dict[str, float] | None


def _feature_ranges(examples: list[ExtendedBodyFeatures]) -> dict[str, tuple[float, float]]:
    ranges: dict[str, tuple[float, float]] = {}
    for field in _NUMERIC_FIELDS:
        values = [getattr(e, field) for e in examples]
        ranges[field] = (min(values), max(values))
    return ranges


def _normalize(value: float, lo: float, hi: float) -> float:
    if hi == lo:
        return 0.0
    return (value - lo) / (hi - lo)


def _composition_distance(a: dict[str, float] | None, b: dict[str, float] | None) -> float:
    """L1 distance over the union of keys, normalized to [0,1]. None on
    either side contributes 0 (neutral) -- not every body type carries
    a composition, and a missing value isn't evidence of a mismatch."""
    if a is None or b is None:
        return 0.0
    keys = set(a) | set(b)
    l1 = sum(abs(a.get(k, 0.0) - b.get(k, 0.0)) for k in keys)
    return l1 / _MAX_COMPOSITION_L1_DISTANCE


def _distance(a: ExtendedBodyFeatures, b: ExtendedBodyFeatures, ranges: dict[str, tuple[float, float]]) -> float:
    numeric_terms = []
    for field in _NUMERIC_FIELDS:
        lo, hi = ranges[field]
        numeric_terms.append(_normalize(getattr(a, field), lo, hi) - _normalize(getattr(b, field), lo, hi))
    composition_terms = [_composition_distance(getattr(a, field), getattr(b, field)) for field in _COMPOSITION_FIELDS]
    numeric_distance = math.sqrt(sum(t * t for t in numeric_terms) + sum(t * t for t in composition_terms))

    mismatches = sum(1 for field in _CATEGORICAL_FIELDS if getattr(a, field) != getattr(b, field))
    return numeric_distance + CATEGORICAL_MISMATCH_PENALTY * mismatches


def _nearest_neighbor_species_counts(
    target: ExtendedBodyFeatures,
    fit_examples: list[tuple[ExtendedBodyFeatures, frozenset[str]]],
    k: int,
) -> Counter[str] | None:
    if not fit_examples:
        return None
    ranges = _feature_ranges([f for f, _ in fit_examples])
    ranked = sorted(fit_examples, key=lambda pair: _distance(target, pair[0], ranges))
    neighbors = ranked[:k]
    counter: Counter[str] = Counter()
    for _, species_set in neighbors:
        counter.update(species_set)
    return counter


def predict_species_membership_probabilities(
    target: ExtendedBodyFeatures,
    fit_examples: list[tuple[ExtendedBodyFeatures, frozenset[str]]],
    k: int = NEIGHBOR_COUNT,
) -> dict[str, float] | None:
    """Same marginal-membership semantics as
    app.bio.species_prediction.predict_species_membership_probabilities
    (p(s) = fraction of the k nearest neighbor bodies containing s, does
    NOT sum to 1) -- only the feature/distance definition differs."""
    counter = _nearest_neighbor_species_counts(target, fit_examples, k)
    if counter is None:
        return None
    neighbor_count = min(k, len(fit_examples))
    if neighbor_count == 0:
        return None
    return {species: count / neighbor_count for species, count in counter.items()}
