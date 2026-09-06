"""Species Prediction Backtest — Baseline 0 / Baseline 1.

Spec (docs/BIO_EXTERNAL_DATA_VALIDATION_SPEC_V0.1.md §6.1,
docs/PHASE_BIO_SPECIES_PREDICTION_BACKTEST_DESIGN_BASELINE_V0.1.md §4).
External population only (`BioObservation`) -- this player's own Journal
is never used here (spec §2.1).

Evaluates the simplest model first (Baseline 0: population-mode,
ignoring body conditions entirely) before a more complex one (Baseline
1: k-NN over EDSM body physical parameters) -- same "evaluate the
current/simplest approach before building something new" discipline as
Mining/Trade Formula Validation. Baseline 0 is expected to score badly;
that is the correct, honest first measurement, not a wasted step.

Chronological split is by "when a body was FIRST seen in the
population" (design doc §4.1) -- a body's species composition is a
static game fact, so this isn't a temporal price-like split; it exists
purely to prevent a holdout body's own (future, from the fit model's
perspective) observation from leaking into its own prediction.
"""
from __future__ import annotations

import datetime as dt
import math
from collections import Counter, defaultdict
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.bio.body_parameters import get_body_parameters
from app.db.models.eddn import BioObservation

BodyKey = tuple[int, int]  # (system_address, body_id)

# Frozen before any backtest was run (design doc §4.2's own discipline).
# Larger than the maximum possible normalized-numeric distance (2 axes,
# each min-max scaled to [0,1] -> max Euclidean distance sqrt(2) =~ 1.41),
# so any categorical mismatch always outranks numeric closeness -- exact
# environmental matches are preferred over "numerically close but a
# different atmosphere/volcanism/body type" every time.
CATEGORICAL_MISMATCH_PENALTY = 10.0
NEIGHBOR_COUNT = 5
TOP_K = 3


@dataclass(frozen=True)
class BodyRecord:
    first_observed_at: dt.datetime
    species: frozenset[str]


def collect_body_population(session: Session) -> dict[BodyKey, BodyRecord]:
    """One record per (system_address, body_id): the set of species ever
    observed there, and the earliest observed_at across all of them --
    the timestamp this body "entered" the population, for the
    chronological split (§4.1)."""
    by_body: dict[BodyKey, list[BioObservation]] = defaultdict(list)
    for row in session.query(BioObservation).all():
        by_body[(row.system_address, row.body_id)].append(row)

    population: dict[BodyKey, BodyRecord] = {}
    for key, rows in by_body.items():
        population[key] = BodyRecord(
            first_observed_at=min(r.observed_at for r in rows),
            species=frozenset(r.species for r in rows),
        )
    return population


def split_chronological(
    population: dict[BodyKey, BodyRecord], split_at: dt.datetime
) -> tuple[dict[BodyKey, BodyRecord], dict[BodyKey, BodyRecord]]:
    """fit = first observed at or before split_at; holdout = first
    observed strictly after. No random split (never mixes chronology)."""
    fit = {k: v for k, v in population.items() if v.first_observed_at <= split_at}
    holdout = {k: v for k, v in population.items() if v.first_observed_at > split_at}
    return fit, holdout


def rank_species_by_frequency(fit_population: dict[BodyKey, BodyRecord]) -> list[str]:
    """Baseline 0's whole model: species ranked by how many fit-period
    bodies had them, most common first. Ties broken by species code
    ascending, for determinism."""
    counter: Counter[str] = Counter()
    for record in fit_population.values():
        counter.update(record.species)
    return [species for species, _ in sorted(counter.items(), key=lambda item: (-item[1], item[0]))]


@dataclass(frozen=True)
class BodyFeatures:
    gravity: float
    surface_temperature: float
    atmosphere_type: str | None
    volcanism_type: str | None
    sub_type: str | None


def _feature_ranges(examples: list[BodyFeatures]) -> tuple[tuple[float, float], tuple[float, float]]:
    gravities = [e.gravity for e in examples]
    temps = [e.surface_temperature for e in examples]
    return (min(gravities), max(gravities)), (min(temps), max(temps))


def _normalize(value: float, lo: float, hi: float) -> float:
    if hi == lo:
        return 0.0
    return (value - lo) / (hi - lo)


def _distance(
    a: BodyFeatures,
    b: BodyFeatures,
    gravity_range: tuple[float, float],
    temperature_range: tuple[float, float],
) -> float:
    g_lo, g_hi = gravity_range
    t_lo, t_hi = temperature_range
    numeric = math.dist(
        (_normalize(a.gravity, g_lo, g_hi), _normalize(a.surface_temperature, t_lo, t_hi)),
        (_normalize(b.gravity, g_lo, g_hi), _normalize(b.surface_temperature, t_lo, t_hi)),
    )
    mismatches = sum(
        1
        for field in ("atmosphere_type", "volcanism_type", "sub_type")
        if getattr(a, field) != getattr(b, field)
    )
    return numeric + CATEGORICAL_MISMATCH_PENALTY * mismatches


def predict_knn(
    target: BodyFeatures,
    fit_examples: list[tuple[BodyFeatures, frozenset[str]]],
    k: int = NEIGHBOR_COUNT,
) -> list[str] | None:
    """Ranks species by frequency among the k nearest fit-population
    neighbors (by _distance). None only when there are no fit examples
    at all to compare against (structurally can't predict, not "no
    species found")."""
    if not fit_examples:
        return None
    gravity_range, temperature_range = _feature_ranges([f for f, _ in fit_examples])
    ranked = sorted(fit_examples, key=lambda pair: _distance(target, pair[0], gravity_range, temperature_range))
    neighbors = ranked[:k]
    counter: Counter[str] = Counter()
    for _, species_set in neighbors:
        counter.update(species_set)
    return [species for species, _ in sorted(counter.items(), key=lambda item: (-item[1], item[0]))]


@dataclass(frozen=True)
class PredictionCase:
    key: BodyKey
    actual_species: frozenset[str]
    predicted: list[str] | None  # None = INSUFFICIENT for this body specifically


@dataclass(frozen=True)
class BacktestResult:
    total_holdout: int
    predicted_count: int
    insufficient_count: int
    top1_hits: int
    topk_hits: int
    top1_accuracy: float | None  # None only when predicted_count == 0
    topk_hit_rate: float | None
    coverage: float
    insufficient_rate: float


def evaluate_predictions(cases: list[PredictionCase], top_k: int = TOP_K) -> BacktestResult:
    total = len(cases)
    predicted = [c for c in cases if c.predicted is not None]
    insufficient_count = total - len(predicted)

    top1_hits = sum(1 for c in predicted if c.predicted[0] in c.actual_species)
    topk_hits = sum(1 for c in predicted if any(s in c.actual_species for s in c.predicted[:top_k]))

    return BacktestResult(
        total_holdout=total,
        predicted_count=len(predicted),
        insufficient_count=insufficient_count,
        top1_hits=top1_hits,
        topk_hits=topk_hits,
        top1_accuracy=(top1_hits / len(predicted)) if predicted else None,
        topk_hit_rate=(topk_hits / len(predicted)) if predicted else None,
        coverage=(len(predicted) / total) if total else 0.0,
        insufficient_rate=(insufficient_count / total) if total else 0.0,
    )


def run_baseline0(fit_population: dict[BodyKey, BodyRecord], holdout_population: dict[BodyKey, BodyRecord]) -> BacktestResult:
    ranking = rank_species_by_frequency(fit_population)
    cases = [
        PredictionCase(key=key, actual_species=record.species, predicted=ranking if ranking else None)
        for key, record in holdout_population.items()
    ]
    return evaluate_predictions(cases)


def run_baseline1(
    session: Session,
    fit_population: dict[BodyKey, BodyRecord],
    holdout_population: dict[BodyKey, BodyRecord],
) -> BacktestResult:
    """Only uses bodies with cached EDSM parameters on both sides -- a
    fit-population body with no cached parameters simply can't act as a
    neighbor (silently absent, not a fabricated feature vector); a
    holdout body with no cached parameters is INSUFFICIENT for itself."""
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

    cases: list[PredictionCase] = []
    for key, record in holdout_population.items():
        params = get_body_parameters(session, key[0], key[1])
        if params is None or params.gravity is None or params.surface_temperature is None:
            cases.append(PredictionCase(key=key, actual_species=record.species, predicted=None))
            continue
        target = BodyFeatures(
            gravity=params.gravity, surface_temperature=params.surface_temperature,
            atmosphere_type=params.atmosphere_type, volcanism_type=params.volcanism_type,
            sub_type=params.sub_type,
        )
        predicted = predict_knn(target, fit_examples)
        cases.append(PredictionCase(key=key, actual_species=record.species, predicted=predicted))

    return evaluate_predictions(cases)
