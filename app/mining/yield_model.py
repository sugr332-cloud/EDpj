"""Mining yield — Phase 2-3.

Spec (docs/PHASE_2_3_HORIZON_VALUE_DESIGN_BASELINE_V0.1.md §4.3, v0.4).

Pre-implementation verification against the real Journal schema found
`MiningRefined` carries no quantity field at all — each event fires when
the refinery converts fragments into exactly 1 ton of `Type`, unconditionally.
There is no per-event distribution to fit a statistical model from (the
original v0.3 plan to reuse the Calibration Engine's median approach had
no data to operate on), so this is a fixed constant, not a model.
"""
from __future__ import annotations

EXPECTED_REFINED_QUANTITY_PER_EVENT = 1.0
