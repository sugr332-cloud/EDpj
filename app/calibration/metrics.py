"""Pure calibration metrics — no DB, no session (IMPLEMENTATION_SPEC_V0.2.md §6.2).

```text
absolute_error = abs(predicted - actual) / actual
signed_error   = (predicted - actual) / actual
```

`validation_status` implements the Phase 0-C/2-0 exit criteria exactly:

```text
validation_pass =
    eval_count > 0
    AND median_absolute_error <= 0.20
    AND abs(median_signed_error) <= 0.10
```

Per review: sample count never substitutes for validation. A segment with
plenty of fit samples but a failed (or missing) eval check is not treated
as more trustworthy than one with few — see app/routing/time.py, which
consumes `validation_status` as diagnostic metadata only and never
promotes a calibrated estimate to `measured` regardless of this result.
"""
from __future__ import annotations

import statistics
from typing import Literal, Sequence

MAE_THRESHOLD = 0.20
SIGNED_ERROR_THRESHOLD = 0.10

ValidationStatus = Literal["pass", "fail", "insufficient"]


def median_absolute_error(predicted: float, actuals: Sequence[float]) -> float:
    return statistics.median(abs(predicted - a) / a for a in actuals)


def median_signed_error(predicted: float, actuals: Sequence[float]) -> float:
    return statistics.median((predicted - a) / a for a in actuals)


def r_squared(predicted: float, actuals: Sequence[float]) -> float:
    """Diagnostic only (IMPLEMENTATION_SPEC_V0.2.md §6.2) — never used to
    gate validation_status. Degenerate (zero-variance eval set) returns
    1.0 if the constant predictor happens to match exactly, else 0.0,
    rather than raising a division-by-zero."""
    mean_actual = statistics.mean(actuals)
    ss_tot = sum((a - mean_actual) ** 2 for a in actuals)
    ss_res = sum((a - predicted) ** 2 for a in actuals)
    if ss_tot == 0:
        return 1.0 if ss_res == 0 else 0.0
    return 1 - ss_res / ss_tot


def validation_status(eval_count: int, mae: float | None, signed: float | None) -> ValidationStatus:
    if eval_count == 0 or mae is None or signed is None:
        return "insufficient"
    if mae <= MAE_THRESHOLD and abs(signed) <= SIGNED_ERROR_THRESHOLD:
        return "pass"
    return "fail"
