from __future__ import annotations

from app.backtest.formula_validation import (
    EvaluationCase,
    GateVerdict,
    compute_formula_accuracy,
    is_hit,
    relative_error,
)


class TestRelativeError:
    def test_exact_match_is_zero_error(self):
        assert relative_error(100.0, 100.0) == 0.0

    def test_never_divides_by_zero_actual(self):
        # epsilon guard -- must not raise ZeroDivisionError.
        relative_error(5.0, 0.0)

    def test_hit_at_exactly_the_threshold(self):
        # actual=100, predicted=140 -> relative_error == 0.40 exactly, still a hit (<=).
        assert is_hit(140.0, 100.0) is True

    def test_miss_just_past_the_threshold(self):
        assert is_hit(140.01, 100.0) is False


class TestComputeFormulaAccuracy:
    def test_insufficient_when_below_minimum_cases(self):
        cases = [EvaluationCase(predicted_value=100.0, actual_value=100.0)]
        result = compute_formula_accuracy(cases, minimum_cases=5)
        assert result.verdict == GateVerdict.INSUFFICIENT
        assert result.formula_accuracy is None
        assert result.valid_cases == 1

    def test_insufficient_with_zero_cases_never_fabricates_zero_percent(self):
        result = compute_formula_accuracy([], minimum_cases=1)
        assert result.verdict == GateVerdict.INSUFFICIENT
        assert result.formula_accuracy is None

    def test_zero_actual_cases_excluded_from_denominator_and_counted_separately(self):
        cases = [
            EvaluationCase(predicted_value=10.0, actual_value=0.0),
            EvaluationCase(predicted_value=100.0, actual_value=100.0),
            EvaluationCase(predicted_value=100.0, actual_value=100.0),
        ]
        result = compute_formula_accuracy(cases, minimum_cases=2)
        assert result.valid_cases == 2
        assert result.zero_actual_cases_excluded == 1
        assert result.formula_accuracy == 1.0

    def test_pass_at_exactly_sixty_percent(self):
        hits = [EvaluationCase(predicted_value=100.0, actual_value=100.0) for _ in range(6)]
        misses = [EvaluationCase(predicted_value=1000.0, actual_value=100.0) for _ in range(4)]
        result = compute_formula_accuracy(hits + misses, minimum_cases=1)
        assert result.formula_accuracy == 0.6
        assert result.verdict == GateVerdict.PASS

    def test_fail_just_below_sixty_percent(self):
        hits = [EvaluationCase(predicted_value=100.0, actual_value=100.0) for _ in range(5)]
        misses = [EvaluationCase(predicted_value=1000.0, actual_value=100.0) for _ in range(5)]
        result = compute_formula_accuracy(hits + misses, minimum_cases=1)
        assert result.formula_accuracy == 0.5
        assert result.verdict == GateVerdict.FAIL
