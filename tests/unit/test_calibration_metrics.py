from __future__ import annotations

import pytest

from app.calibration.metrics import (
    MAE_THRESHOLD,
    SIGNED_ERROR_THRESHOLD,
    median_absolute_error,
    median_signed_error,
    r_squared,
    validation_status,
)


def test_median_absolute_error_perfect_prediction_is_zero():
    assert median_absolute_error(100.0, [100.0, 100.0, 100.0]) == 0.0


def test_median_absolute_error_is_unsigned():
    # predicted too high and too low should contribute equally
    assert median_absolute_error(110.0, [100.0]) == pytest.approx(0.10)
    assert median_absolute_error(90.0, [100.0]) == pytest.approx(0.10)


def test_median_signed_error_direction_matters():
    over = median_signed_error(110.0, [100.0])  # predicted too high
    under = median_signed_error(90.0, [100.0])  # predicted too low
    assert over > 0
    assert under < 0


def test_r_squared_perfect_prediction_is_one():
    assert r_squared(100.0, [100.0, 100.0, 100.0]) == 1.0


def test_r_squared_zero_variance_eval_set_does_not_raise():
    # every eval value identical -> ss_tot == 0; must not divide by zero
    assert r_squared(50.0, [100.0, 100.0]) == 0.0
    assert r_squared(100.0, [100.0, 100.0]) == 1.0


class TestValidationStatus:
    def test_zero_eval_count_is_insufficient(self):
        assert validation_status(0, None, None) == "insufficient"

    def test_within_thresholds_is_pass(self):
        assert validation_status(10, MAE_THRESHOLD, SIGNED_ERROR_THRESHOLD) == "pass"
        assert validation_status(10, 0.05, -0.05) == "pass"

    def test_mae_over_threshold_is_fail(self):
        assert validation_status(10, MAE_THRESHOLD + 0.01, 0.0) == "fail"

    def test_signed_error_over_threshold_is_fail(self):
        assert validation_status(10, 0.05, SIGNED_ERROR_THRESHOLD + 0.01) == "fail"
        assert validation_status(10, 0.05, -(SIGNED_ERROR_THRESHOLD + 0.01)) == "fail"
