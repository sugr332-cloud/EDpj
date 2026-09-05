"""Calibration result value object — the in-memory counterpart of
`app.db.models.calibration.CalibrationModel` (that's the persisted row;
this is what `engine.fit_segment` computes before writing one)."""
from __future__ import annotations

from dataclasses import dataclass

from app.calibration.metrics import ValidationStatus


@dataclass(frozen=True)
class CalibrationResult:
    segment_type: str
    seconds: float | None
    sample_count_fit: int
    sample_count_eval: int
    median_absolute_error: float | None
    median_signed_error: float | None
    r_squared: float | None
    validation_status: ValidationStatus
