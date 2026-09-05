from __future__ import annotations

from app.routing.time import estimate_segment


def test_supercruise_is_always_unavailable_without_touching_the_database():
    # The supercruise branch must return before ever querying
    # calibration_models -- passing session=None proves it (any DB access
    # here would raise AttributeError on None).
    result = estimate_segment("supercruise", None, None)
    assert result.status == "unavailable"
    assert result.seconds is None
    assert result.confidence is None
    assert result.basis  # non-empty explanation
