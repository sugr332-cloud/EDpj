"""Stored per-segment calibration results.

Spec (IMPLEMENTATION_SPEC_V0.2.md §6.1/§6.2, docs/PHASE_2_0_DESIGN_BASELINE_V0.1.md):
one row per segment_type (jump/dock/undock/descent/ascent/mining_cycle/
bio_sample — supercruise is never calibrated, see app/routing/time.py).
`seconds` is the fit-set median; `validation_status` records whether the
held-out eval set actually confirmed that estimate (median_absolute_error
<= 20% AND |median_signed_error| <= 10%), independent of sample count.

Per review: sample count alone never promotes a row to "measured" — this
table's output is always consumed as `estimated` (see app/routing/time.py's
estimate_segment). `validation_status` is diagnostic metadata that a later
confidence-design phase may use to further discount confidence; Phase 2-1
does not do that yet.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class CalibrationModel(Base):
    __tablename__ = "calibration_models"
    __table_args__ = (UniqueConstraint("segment_type", name="uq_calibration_model_segment_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    segment_type: Mapped[str] = mapped_column(String, nullable=False, index=True)

    seconds: Mapped[float | None] = mapped_column(Float, nullable=True)  # fit-set median; None if no fit data
    sample_count_fit: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sample_count_eval: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    median_absolute_error: Mapped[float | None] = mapped_column(Float, nullable=True)
    median_signed_error: Mapped[float | None] = mapped_column(Float, nullable=True)
    r_squared: Mapped[float | None] = mapped_column(Float, nullable=True)  # diagnostic only, never gates anything

    # 'pass' | 'fail' | 'insufficient' (insufficient = sample_count_eval == 0,
    # or sample_count_fit == 0 -- see app/calibration/metrics.py's validation_status()).
    validation_status: Mapped[str] = mapped_column(String, nullable=False, default="insufficient")

    fitted_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: dt.datetime.now(dt.timezone.utc)
    )
