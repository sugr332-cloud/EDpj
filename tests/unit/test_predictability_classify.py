from __future__ import annotations

from app.market.predictability import (
    MIN_SAMPLES_FOR_CLASSIFICATION,
    MODERATE_MEDIAN_PRICE_CHANGE,
    STABLE_MEDIAN_PRICE_CHANGE,
    classify,
)


def test_insufficient_when_sample_count_below_minimum():
    assert classify(MIN_SAMPLES_FOR_CLASSIFICATION - 1, median_abs_price_change=0.01) == "INSUFFICIENT"


def test_insufficient_when_median_price_change_is_none():
    assert classify(MIN_SAMPLES_FOR_CLASSIFICATION + 5, median_abs_price_change=None) == "INSUFFICIENT"


def test_stable_below_threshold():
    assert classify(MIN_SAMPLES_FOR_CLASSIFICATION, STABLE_MEDIAN_PRICE_CHANGE - 0.001) == "STABLE"


def test_moderate_between_thresholds():
    midpoint = (STABLE_MEDIAN_PRICE_CHANGE + MODERATE_MEDIAN_PRICE_CHANGE) / 2
    assert classify(MIN_SAMPLES_FOR_CLASSIFICATION, midpoint) == "MODERATE"


def test_volatile_at_or_above_moderate_threshold():
    assert classify(MIN_SAMPLES_FOR_CLASSIFICATION, MODERATE_MEDIAN_PRICE_CHANGE) == "VOLATILE"
    assert classify(MIN_SAMPLES_FOR_CLASSIFICATION, MODERATE_MEDIAN_PRICE_CHANGE + 1.0) == "VOLATILE"


def test_classify_signature_has_no_demand_parameter():
    # Structural guarantee, not just a convention: demand volatility
    # cannot influence classification because the function has no
    # parameter to pass it through (docs/PHASE_2_5A... §7/§10 decision 3).
    import inspect

    params = list(inspect.signature(classify).parameters)
    assert params == ["sample_count", "median_abs_price_change"]
