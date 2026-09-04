"""Phase 0-B timing samples.

Spec (IMPLEMENTATION_SPEC_V0.2 section 5): one row per completed
start-event -> end-event pair. `start_file_name`/`start_line_number` double
as both provenance and a natural dedup key (re-running backfill must not
duplicate samples) and, later, as the session key Phase 0-C's chronological
fit/eval split uses to avoid splitting a single play session across the
boundary.

`route_plot_samples` is deliberately separate: it has no `duration_seconds`
notion (a route can span many jumps) and stores JSON leg data rather than a
single start/end pair.

`arrival_dist_from_star_ls` (supercruise rows only) is the terminating
Docked event's `DistFromStarLS` — that station's static distance from the
system's main star, NOT the distance actually traveled during the
supercruise leg (Elite Dangerous's journal has no such field, and the SC
start position generally isn't known either). Do not use it as
distance-to-duration calibration training data; see app/journal/timing.py's
module docstring for the full reasoning. `duration_seconds` itself is a
valid timing sample regardless of `reached_known_target`.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class TimingSample(Base):
    __tablename__ = "timing_samples"
    __table_args__ = (
        UniqueConstraint(
            "segment_type",
            "start_file_name",
            "start_line_number",
            "end_file_name",
            "end_line_number",
            name="uq_timing_sample_pair",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    segment_type: Mapped[str] = mapped_column(String, nullable=False, index=True)

    start_file_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    start_line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    end_file_name: Mapped[str] = mapped_column(String, nullable=False)
    end_line_number: Mapped[int] = mapped_column(Integer, nullable=False)

    start_time: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    end_time: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)

    arrival_dist_from_star_ls: Mapped[float | None] = mapped_column(Float, nullable=True)
    reached_known_target: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    extra: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    inserted_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: dt.datetime.now(dt.timezone.utc)
    )


class RoutePlotSample(Base):
    __tablename__ = "route_plot_samples"
    __table_args__ = (
        UniqueConstraint("navroute_file_name", "navroute_line_number", name="uq_route_plot_sample"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    navroute_file_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    navroute_line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    systems: Mapped[list] = mapped_column(JSON, nullable=False)
    completed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    leg_arrivals: Mapped[list] = mapped_column(JSON, nullable=False)
    inserted_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: dt.datetime.now(dt.timezone.utc)
    )
