from __future__ import annotations

from app.scoring.models import is_scoreable
from app.scoring.value import calculate_score


def test_is_scoreable_true_when_all_three_conditions_met():
    assert is_scoreable([], 100.0, None) is True


def test_is_scoreable_false_when_horizon_blocked():
    assert is_scoreable(["supercruise"], 100.0, None) is False


def test_is_scoreable_false_when_value_missing():
    assert is_scoreable([], None, None) is False


def test_is_scoreable_false_when_value_unavailable_reason_set():
    assert is_scoreable([], 100.0, "cargo_capacity_unknown") is False


def test_calculate_score_divides_value_by_horizon_hours():
    assert calculate_score(expected_value=3600.0, action_horizon_seconds=3600.0) == 3600.0
    assert calculate_score(expected_value=1000.0, action_horizon_seconds=1800.0) == 2000.0
