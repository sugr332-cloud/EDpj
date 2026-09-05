"""Formula Validation Gate accuracy math — Phase 2-6F.

Spec (docs/ABSOLUTE_FORMULA_VALIDATION_GATE_V0.1.md §2/§6,
docs/PHASE_2_6F_FORMULA_VALIDATION_GATE_DESIGN_BASELINE_V0.1.md). Generic
accuracy-gate primitives shared by every Formula Validation target
(Mining first, per the fixed evaluation order; Bio next) -- this module
knows nothing about Mining/Bio/Trade specifics, only how to turn a list
of (predicted, actual) pairs into a PASS/FAIL/INSUFFICIENT verdict.

`minimum_cases` is always supplied by the caller rather than hardcoded
here -- the binding spec explicitly forbids lowering it just to
manufacture a PASS (§6), so each Formula Validation target picks its own
threshold from its own real data distribution, not from a shared
constant that could be quietly tuned in one place to affect every
target at once.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

RELATIVE_ERROR_HIT_THRESHOLD = 0.40  # ABSOLUTE_FORMULA_VALIDATION_GATE_V0.1.md §2
FORMULA_ACCURACY_PASS_THRESHOLD = 0.60  # same doc, §2
EPSILON = 1e-9


@dataclass(frozen=True)
class EvaluationCase:
    predicted_value: float
    actual_value: float


class GateVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INSUFFICIENT = "INSUFFICIENT"


@dataclass(frozen=True)
class FormulaAccuracyResult:
    verdict: GateVerdict
    formula_accuracy: float | None  # None only when verdict is INSUFFICIENT
    valid_cases: int
    zero_actual_cases_excluded: int
    minimum_cases: int


def relative_error(predicted: float, actual: float) -> float:
    return abs(predicted - actual) / max(abs(actual), EPSILON)


def is_hit(predicted: float, actual: float) -> bool:
    return relative_error(predicted, actual) <= RELATIVE_ERROR_HIT_THRESHOLD


def compute_formula_accuracy(cases: list[EvaluationCase], minimum_cases: int) -> FormulaAccuracyResult:
    """§2: `actual_value == 0` cases can't define a relative error (the
    denominator would be meaningless even with the epsilon guard), so
    they're excluded from the accuracy denominator and counted
    separately rather than silently dropped without a trace. §6:
    `valid_cases < minimum_cases` is always `INSUFFICIENT`, never a
    fabricated 0%/100% accuracy -- an empty formula_accuracy (None) is
    the only correct value when there's nothing to compute from."""
    zero_actual = [c for c in cases if c.actual_value == 0]
    valid = [c for c in cases if c.actual_value != 0]
    if len(valid) < minimum_cases:
        return FormulaAccuracyResult(
            verdict=GateVerdict.INSUFFICIENT,
            formula_accuracy=None,
            valid_cases=len(valid),
            zero_actual_cases_excluded=len(zero_actual),
            minimum_cases=minimum_cases,
        )
    hits = sum(1 for c in valid if is_hit(c.predicted_value, c.actual_value))
    accuracy = hits / len(valid)
    verdict = GateVerdict.PASS if accuracy >= FORMULA_ACCURACY_PASS_THRESHOLD else GateVerdict.FAIL
    return FormulaAccuracyResult(
        verdict=verdict,
        formula_accuracy=accuracy,
        valid_cases=len(valid),
        zero_actual_cases_excluded=len(zero_actual),
        minimum_cases=minimum_cases,
    )
