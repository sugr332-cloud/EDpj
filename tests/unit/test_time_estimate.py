from __future__ import annotations

from app.routing.time import (
    ESTIMATED_CONFIDENCE_CEILING,
    ESTIMATED_CONFIDENCE_FLOOR,
    MEASURED_CONFIDENCE,
    MEASURED_SAMPLE_THRESHOLD,
    _estimated_confidence,
    _summarize,
)


def test_zero_durations_is_unavailable():
    result = _summarize("dock", [])
    assert result.status == "unavailable"
    assert result.seconds is None
    assert result.confidence is None
    assert result.basis  # non-empty explanation


def test_below_threshold_is_estimated():
    durations = [10.0, 12.0, 11.0]  # 3 samples, well below MEASURED_SAMPLE_THRESHOLD
    result = _summarize("mining_cycle", durations)
    assert result.status == "estimated"
    assert result.seconds == 11.0  # median
    assert ESTIMATED_CONFIDENCE_FLOOR <= result.confidence < MEASURED_CONFIDENCE
    assert "sample_count=3" in result.basis


def test_at_or_above_threshold_is_measured():
    durations = [10.0] * MEASURED_SAMPLE_THRESHOLD
    result = _summarize("dock", durations)
    assert result.status == "measured"
    assert result.seconds == 10.0
    assert result.confidence == MEASURED_CONFIDENCE
    assert f"sample_count={MEASURED_SAMPLE_THRESHOLD}" in result.basis


def test_estimated_confidence_scales_with_sample_count():
    low = _estimated_confidence(1)
    high = _estimated_confidence(MEASURED_SAMPLE_THRESHOLD - 1)
    assert ESTIMATED_CONFIDENCE_FLOOR <= low < high < MEASURED_CONFIDENCE
    assert high <= ESTIMATED_CONFIDENCE_CEILING


def test_estimated_confidence_never_reaches_measured_confidence():
    # even just below the threshold, estimated must stay a distinct, lower tier
    assert _estimated_confidence(MEASURED_SAMPLE_THRESHOLD - 1) < MEASURED_CONFIDENCE
