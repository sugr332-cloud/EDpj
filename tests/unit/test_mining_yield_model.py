from __future__ import annotations

from app.mining.yield_model import EXPECTED_REFINED_QUANTITY_PER_EVENT


def test_expected_quantity_is_a_fixed_one_ton_per_event():
    # docs/PHASE_2_3_HORIZON_VALUE_DESIGN_BASELINE_V0.1.md §4.3 (v0.4):
    # MiningRefined carries no quantity field -- this is a game-mechanic
    # constant, not a statistical estimate.
    assert EXPECTED_REFINED_QUANTITY_PER_EVENT == 1.0
